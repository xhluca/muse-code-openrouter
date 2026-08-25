"""Muse Code to OpenRouter protocol adapter."""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import ssl
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .install import DEFAULT_MODEL, is_muse_model_id, model_catalog_row
from .rewrite import restore_response, rewrite_request

LOG = logging.getLogger("muse-code-openrouter")
DEFAULT_UPSTREAM = "https://openrouter.ai/api/v1"
DEFAULT_OUTPUT_LIMIT = 16_384
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
PRIVATE_MUSE_HEADERS = {
    "x-tbh-session-id",
    "x-client-id",
    "traceparent",
    "x-fb-client-id",
}


def translate_catalog(payload: Any, selected_model: str) -> dict[str, Any]:
    """Translate OpenRouter's catalog into the schema required by Muse Code."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("OpenRouter returned an invalid model catalog")
    models = [
        item
        for item in payload["data"]
        if isinstance(item, dict) and is_muse_model_id(item.get("id"))
    ]
    models.sort(key=lambda item: item["id"])
    if selected_model not in {item["id"] for item in models}:
        raise ValueError(f"model is not available on OpenRouter: {selected_model}")
    rows = []
    for index, metadata in enumerate(models):
        row = model_catalog_row(
            metadata, selected_model=selected_model, display_order=index
        )
        row["id"] = metadata["id"]
        rows.append(row)
    return {"data": rows}


def select_request_model(payload: Any, default_model: str) -> str:
    """Select an explicitly requested Meta Muse model or the configured default."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    requested = payload.get("model", default_model)
    if not is_muse_model_id(requested):
        raise ValueError("model must be an OpenRouter meta/muse* model")
    return requested


def enforce_output_limit(payload: dict[str, Any], output_limit: int) -> None:
    """Clamp Muse's large default output budget to the advertised model limit."""
    for field in ("max_output_tokens", "max_tokens"):
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > output_limit:
            payload[field] = output_limit


def rewrite_sse_block(
    block: bytes, alias_to_original: dict[str, str], sequence_number: int
) -> tuple[bytes, bool]:
    """Normalize one SSE block for Muse Code and report whether it was numbered."""
    text = block.decode("utf-8", errors="replace").replace("\r\n", "\n")
    event: str | None = None
    data_lines: list[str] = []
    other_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line.partition(":")[2].strip()
        elif line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
        elif line:
            other_lines.append(line)
    if not data_lines:
        rendered = "\n".join(other_lines)
        return (rendered + "\n\n").encode(), False
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return b"data: [DONE]\n\n", False
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return (f"data: {data}\n\n").encode(), False
    if not isinstance(payload, dict):
        return (f"data: {data}\n\n").encode(), False
    payload = restore_response(payload, alias_to_original)
    payload.setdefault("sequence_number", sequence_number)
    if event is None and isinstance(payload.get("type"), str):
        event = payload["type"]
    prefix = f"event: {event}\n" if event else ""
    data = json.dumps(payload, separators=(",", ":"))
    return f"{prefix}data: {data}\n\n".encode(), True


class MuseOpenRouterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MuseCodeOpenRouter/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/") == "/healthz":
            self._json_response(200, {"status": "ok"})
            return
        if self.path.split("?", 1)[0].rstrip("/") in {"/muse-code/models", "/models"}:
            self._serve_catalog()
            return
        self._json_response(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0].rstrip("/").endswith("/responses"):
            self._serve_responses()
            return
        self._json_response(404, {"error": {"message": "not found"}})

    @property
    def adapter(self) -> MuseOpenRouterServer:
        return self.server  # type: ignore[return-value]

    def _connection(self) -> tuple[http.client.HTTPConnection, str]:
        target = urlsplit(self.adapter.upstream)
        if target.scheme not in {"http", "https"} or not target.hostname:
            raise ValueError("invalid OpenRouter upstream URL")
        cls = (
            http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        )
        kwargs: dict[str, Any] = {"timeout": 600}
        if target.scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        return cls(target.hostname, target.port, **kwargs), target.path.rstrip("/")

    def _upstream_headers(self, content_length: int | None = None) -> dict[str, str]:
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in HOP_BY_HOP
            | PRIVATE_MUSE_HEADERS
            | {"host", "authorization", "content-length", "accept-encoding", "user-agent"}
        }
        headers.update(
            {
                "Authorization": f"Bearer {self.adapter.api_key}",
                "Accept-Encoding": "identity",
                "X-Title": "Muse Code OpenRouter",
            }
        )
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
            headers.setdefault("Content-Type", "application/json")
            headers["Accept"] = "text/event-stream"
        return headers

    def _serve_catalog(self) -> None:
        connection, base_path = self._connection()
        try:
            connection.request("GET", f"{base_path}/models", headers=self._upstream_headers())
            response = connection.getresponse()
            body = response.read()
            if response.status >= 400:
                self._buffered_upstream(
                    response.status, response.reason, response.getheaders(), body
                )
                return
            translated = translate_catalog(json.loads(body), self.adapter.model)
            self.adapter.output_limits = {
                row["model_id"]: row["output_limit"] for row in translated["data"]
            }
            self._json_response(200, translated)
        except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException) as exc:
            LOG.error("catalog request failed: %s", exc)
            self._json_response(502, {"error": {"message": str(exc)}})
        finally:
            connection.close()

    def _serve_responses(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        aliases: dict[str, str] = {}
        try:
            payload = json.loads(body)
            selected_model = select_request_model(payload, self.adapter.model)
            payload["model"] = selected_model
            enforce_output_limit(
                payload,
                self.adapter.output_limits.get(selected_model, DEFAULT_OUTPUT_LIMIT),
            )
            payload, aliases = rewrite_request(payload)
            body = json.dumps(payload, separators=(",", ":")).encode()
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self._json_response(400, {"error": {"message": f"invalid request JSON: {exc}"}})
            return

        connection, base_path = self._connection()
        try:
            connection.request(
                "POST",
                f"{base_path}/responses",
                body=body,
                headers=self._upstream_headers(len(body)),
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            if response.status >= 400 or "text/event-stream" not in content_type:
                upstream_body = response.read()
                self._buffered_upstream(
                    response.status, response.reason, response.getheaders(), upstream_body
                )
                return
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in HOP_BY_HOP | {"content-length", "content-encoding"}:
                    self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            pending = b""
            sequence = 0
            while True:
                piece = response.read(8192)
                if not piece:
                    break
                pending += piece.replace(b"\r\n", b"\n")
                while b"\n\n" in pending:
                    block, pending = pending.split(b"\n\n", 1)
                    if not block.strip():
                        continue
                    encoded, numbered = rewrite_sse_block(block, aliases, sequence)
                    if numbered:
                        sequence += 1
                    self._write_chunk(encoded)
            if pending.strip():
                encoded, _ = rewrite_sse_block(pending, aliases, sequence)
                self._write_chunk(encoded)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            LOG.info("Muse Code closed the response stream")
        except (OSError, ValueError, http.client.HTTPException) as exc:
            LOG.error("inference request failed: %s", exc)
            if not self.wfile.closed:
                with suppress(OSError):
                    self._json_response(502, {"error": {"message": "OpenRouter request failed"}})
        finally:
            connection.close()

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode())
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _json_response(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _buffered_upstream(
        self,
        status: int,
        reason: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> None:
        self.send_response(status, reason)
        for key, value in headers:
            if key.lower() not in HOP_BY_HOP | {"content-length", "content-encoding"}:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MuseOpenRouterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        api_key: str,
        model: str,
        upstream: str = DEFAULT_UPSTREAM,
    ):
        super().__init__(address, MuseOpenRouterHandler)
        self.api_key = api_key
        self.model = model
        self.upstream = upstream.rstrip("/")
        self.output_limits: dict[str, int] = {}


def serve(
    host: str,
    port: int,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    upstream: str = DEFAULT_UPSTREAM,
) -> None:
    server = MuseOpenRouterServer((host, port), api_key=api_key, model=model, upstream=upstream)
    LOG.info("listening on http://%s:%d for model %s", host, port, model)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def proxy_main(argv: list[str] | None = None) -> int:
    from .install import read_credential

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("MUSE_OPENROUTER_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MUSE_OPENROUTER_PORT", "8817"))
    )
    parser.add_argument("--model", default=os.environ.get("MUSE_OPENROUTER_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--upstream", default=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_UPSTREAM)
    )
    parser.add_argument("--log-level", default=os.environ.get("MUSE_OPENROUTER_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    serve(
        args.host,
        args.port,
        api_key=read_credential(),
        model=args.model,
        upstream=args.upstream,
    )
    return 0
