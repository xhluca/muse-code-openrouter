import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from muse_code_openrouter.proxy import (
    ModelReplayTracker,
    MuseOpenRouterServer,
    enforce_output_limit,
    is_cross_model_encrypted_error,
    rewrite_sse_block,
    select_request_model,
    translate_catalog,
)


def test_catalog_translation_for_all_muse_models() -> None:
    payload = {
        "data": [
            {"id": "other/model", "name": "Other", "context_length": 10},
            {
                "id": "meta/muse-spark-1.2",
                "name": "Meta: Muse Spark 1.2",
                "context_length": 1_048_576,
                "top_provider": {"max_completion_tokens": 65_536},
            },
            {
                "id": "meta/muse-spark-1.2-contributor",
                "name": "Meta: Muse Spark 1.2 Contributor",
                "context_length": 1_048_576,
            },
        ]
    }
    translated = translate_catalog(payload, "meta/muse-spark-1.2")
    assert translated["schema_version"] == 1
    rows = translated["data"]
    assert [row["model_id"] for row in rows] == [
        "meta/muse-spark-1.2",
        "meta/muse-spark-1.2-contributor",
    ]
    assert all(row["provider_id"] == "meta" for row in rows)
    assert all(row["profile_id"] == "tbh" for row in rows)
    assert [row["model_id"] for row in rows if row["is_default"]] == [
        "meta/muse-spark-1.2"
    ]
    assert rows[0]["context_limit"] == 1_048_576
    assert rows[0]["output_limit"] == 16_384
    assert rows[0]["is_current"] is True
    assert rows[1]["display_label"].startswith("WARNING:")


def test_catalog_rejects_missing_model() -> None:
    with pytest.raises(ValueError, match="not available"):
        translate_catalog({"data": []}, "meta/muse-spark-1.2")


def test_request_preserves_any_meta_muse_model() -> None:
    contributor = "meta/muse-spark-1.2-contributor"
    assert select_request_model({"model": contributor}, "meta/muse-spark-1.2") == contributor
    assert select_request_model({}, "meta/muse-spark-1.2") == "meta/muse-spark-1.2"


def test_request_rejects_non_muse_model() -> None:
    with pytest.raises(ValueError, match=r"meta/muse\*"):
        select_request_model({"model": "openai/gpt-5"}, "meta/muse-spark-1.2")


def test_large_muse_output_budget_is_clamped() -> None:
    payload = {"max_output_tokens": 128_000, "max_tokens": 32_000}
    enforce_output_limit(payload, 16_384)
    assert payload == {"max_output_tokens": 16_384, "max_tokens": 16_384}


def test_sse_adds_event_and_sequence_number() -> None:
    block, numbered = rewrite_sse_block(
        b'data: {"type":"response.output_text.delta","delta":"ok"}', {}, 7
    )
    assert numbered is True
    assert block.startswith(b"event: response.output_text.delta\n")
    payload = json.loads(block.split(b"data: ", 1)[1])
    assert payload["sequence_number"] == 7


def test_sse_preserves_done() -> None:
    assert rewrite_sse_block(b"data: [DONE]", {}, 0) == (b"data: [DONE]\n\n", False)


def test_sse_restores_tool_alias() -> None:
    block, _ = rewrite_sse_block(
        b'data: {"type":"response.output_item.done","item":{"name":"short"}}',
        {"short": "original_long_name"},
        0,
    )
    payload = json.loads(block.split(b"data: ", 1)[1])
    assert payload["item"]["name"] == "original_long_name"


def test_model_switch_blocks_old_encrypted_state_but_keeps_new_state() -> None:
    tracker = ModelReplayTracker()
    session = "session-1"
    old_reasoning = {"type": "reasoning", "encrypted_content": "spark-state"}
    message = {"role": "user", "content": "hello"}

    initial, removed, switched = tracker.prepare(
        session, "meta/muse-spark-1.1", {"input": [message, old_reasoning]}
    )
    assert initial["input"] == [message, old_reasoning]
    assert (removed, switched) == (0, False)

    changed, removed, switched = tracker.prepare(
        session,
        "meta/muse-glimmer-30b",
        {"input": [message, old_reasoning], "previous_response_id": "spark-response"},
    )
    assert changed == {"input": [message]}
    assert (removed, switched) == (1, True)

    new_reasoning = {"type": "reasoning", "encrypted_content": "glimmer-state"}
    continued, removed, switched = tracker.prepare(
        session, "meta/muse-glimmer-30b", {"input": [old_reasoning, new_reasoning]}
    )
    assert continued["input"] == [new_reasoning]
    assert (removed, switched) == (1, False)


def test_cross_model_error_detection_is_specific() -> None:
    body = json.dumps(
        {
            "error": {
                "message": (
                    "Your request contains encrypted reasoning or compaction content that was "
                    "produced under a different model."
                )
            }
        }
    ).encode()
    assert is_cross_model_encrypted_error(404, body)
    assert not is_cross_model_encrypted_error(401, body)
    assert not is_cross_model_encrypted_error(404, b'{"error":{"message":"not found"}}')


def test_proxy_recovers_from_cross_model_encrypted_error() -> None:
    received: list[dict] = []

    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            if len(received) == 1:
                body = json.dumps(
                    {
                        "error": {
                            "message": (
                                "Your request contains encrypted reasoning or compaction content "
                                "that was produced under a different model."
                            )
                        }
                    }
                ).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
            else:
                body = b'data: {"type":"response.completed"}\n\ndata: [DONE]\n\n'
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    adapter = MuseOpenRouterServer(
        ("127.0.0.1", 0),
        api_key="test-key",
        model="meta/muse-spark-1.1",
        upstream=f"http://127.0.0.1:{upstream.server_port}/api/v1",
    )
    adapter_thread = threading.Thread(target=adapter.serve_forever, daemon=True)
    adapter_thread.start()
    try:
        request_payload = {
            "model": "meta/muse-glimmer-30b",
            "previous_response_id": "spark-response",
            "input": [
                {"role": "user", "content": "keep me"},
                {"type": "reasoning", "encrypted_content": "spark-state"},
            ],
        }
        body = json.dumps(request_payload).encode()
        connection = http.client.HTTPConnection("127.0.0.1", adapter.server_port)
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers={"Content-Type": "application/json", "X-TBH-Session-ID": "session-1"},
        )
        response = connection.getresponse()
        response_body = response.read()
        connection.close()

        assert response.status == 200
        assert b"response.completed" in response_body
        assert len(received) == 2
        assert received[0]["input"][1]["encrypted_content"] == "spark-state"
        assert received[1]["input"] == [{"role": "user", "content": "keep me"}]
        assert "previous_response_id" not in received[1]
    finally:
        adapter.shutdown()
        adapter.server_close()
        upstream.shutdown()
        upstream.server_close()
