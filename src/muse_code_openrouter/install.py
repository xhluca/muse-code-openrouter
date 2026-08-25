"""Secure user-level setup and diagnostics for Muse Code."""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8817
DEFAULT_MODEL = "meta/muse-spark-1.2"
MUSE_MODEL_PATTERN = re.compile(r"^meta/muse[A-Za-z0-9._:-]*$")
KEY_PATTERN = re.compile(r"^sk-or-v1-[A-Za-z0-9_-]{20,}$")


def config_dir() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "muse-code-openrouter"


def state_dir() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "muse-code-openrouter"


def credential_path() -> Path:
    override = os.environ.get("MUSE_CODE_OPENROUTER_CREDENTIAL_FILE")
    return Path(override).expanduser() if override else config_dir() / "credential"


def muse_settings_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "muse" / "settings.json"


def muse_executable() -> str | None:
    return shutil.which("muse") or (
        str(Path.home() / ".local" / "bin" / "muse")
        if (Path.home() / ".local" / "bin" / "muse").is_file()
        else None
    )


def executable_path() -> str:
    found = shutil.which("muse-openrouter")
    return found or str(Path(sys.argv[0]).resolve())


def read_credential() -> str:
    path = credential_path()
    try:
        key = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"OpenRouter credential not found at {path}; run setup") from exc
    if not KEY_PATTERN.fullmatch(key):
        raise RuntimeError(f"OpenRouter credential at {path} has an unexpected format")
    return key


def write_credential(key: str) -> Path:
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("the OpenRouter key has an unexpected format")
    path = credential_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{key}\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _openrouter_json(url: str, key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read())
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = f": {error['message']}"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        raise RuntimeError(f"OpenRouter rejected the request (HTTP {exc.code}){detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenRouter returned an invalid JSON response")
    return payload


def validate_key(key: str) -> None:
    _openrouter_json("https://openrouter.ai/api/v1/key", key)


def fetch_model(key: str, model: str) -> dict[str, Any]:
    if not is_muse_model_id(model):
        raise ValueError("model must be an OpenRouter meta/muse* model")
    payload = _openrouter_json(f"https://openrouter.ai/api/v1/model/{model}", key)
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("id") != model:
        raise RuntimeError(f"OpenRouter model is not available: {model}")
    return data


def is_muse_model_id(model: Any) -> bool:
    """Return whether a model id is inside the adapter's Meta Muse boundary."""
    return isinstance(model, str) and MUSE_MODEL_PATTERN.fullmatch(model) is not None


def fetch_muse_models(key: str) -> list[dict[str, Any]]:
    """Fetch every currently available OpenRouter ``meta/muse*`` model."""
    payload = _openrouter_json("https://openrouter.ai/api/v1/models", key)
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("OpenRouter returned an invalid model catalog")
    models = [
        item
        for item in data
        if isinstance(item, dict) and is_muse_model_id(item.get("id"))
    ]
    models.sort(key=lambda item: item["id"])
    if not models:
        raise RuntimeError("OpenRouter did not return any meta/muse* models")
    return models


def model_catalog_row(
    metadata: dict[str, Any], *, selected_model: str, display_order: int
) -> dict[str, Any]:
    model = metadata.get("id")
    if not is_muse_model_id(model):
        raise ValueError("model catalog row is not a meta/muse* model")
    context = _positive_int(metadata.get("context_length"), 128_000)
    provider = metadata.get("top_provider")
    output = _positive_int(
        provider.get("max_completion_tokens") if isinstance(provider, dict) else None,
        min(16_384, context),
    )
    return {
        "model_id": model,
        "provider_id": "meta",
        "profile_id": "tbh",
        "display_label": metadata.get("name") or model,
        "visibility": "visible",
        "display_order": display_order,
        "is_default": model == selected_model,
        "context_limit": context,
        "output_limit": min(output, context),
        "description": "Served through OpenRouter",
    }


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def patch_settings_document(
    existing: dict[str, Any], *, model: str, port: int
) -> dict[str, Any]:
    updated = dict(existing)
    updated.setdefault("schema_version", 1)
    updated["provider"] = "meta"
    updated["model"] = model
    updated["endpoint_transport"] = {
        "base_url": f"http://127.0.0.1:{port}/v1",
        "auth": "none",
    }
    # Let Muse fetch the live catalog from the loopback adapter. Removing an old
    # static catalog also makes newly released meta/muse* models appear without
    # another setup run.
    updated.pop("model_catalog", None)
    return updated


def write_muse_settings(model: str, port: int) -> Path:
    path = muse_settings_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Muse settings are not valid JSON: {path}") from exc
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Muse settings must contain a JSON object: {path}")
        existing = loaded

    backup_dir = state_dir()
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    backup = backup_dir / "settings.before-openrouter.json"
    absent_marker = backup_dir / "settings.was-absent"
    if not backup.exists() and not absent_marker.exists():
        if path.exists():
            shutil.copy2(path, backup)
            os.chmod(backup, 0o600)
        else:
            absent_marker.write_text("\n", encoding="ascii")
            os.chmod(absent_marker, 0o600)

    updated = patch_settings_document(existing, model=model, port=port)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return path


def write_systemd_unit(model: str, port: int) -> Path:
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = unit_dir / "muse-code-openrouter.service"
    unit = f"""[Unit]
Description=OpenRouter adapter for Meta Muse Code
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={executable_path()} serve --host 127.0.0.1 --port {port} --model {model}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
"""
    path.write_text(unit, encoding="utf-8")
    return path


def start_service(model: str, port: int, *, use_systemd: bool = True) -> str:
    if use_systemd and shutil.which("systemctl"):
        write_systemd_unit(model, port)
        commands = [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "muse-code-openrouter.service"],
            ["systemctl", "--user", "restart", "muse-code-openrouter.service"],
        ]
        if all(
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
            for command in commands
        ):
            return "systemd user service"

    runtime = state_dir()
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = runtime / "proxy.log"
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            [
                executable_path(),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--model",
                model,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (runtime / "proxy.pid").write_text(f"{process.pid}\n", encoding="ascii")
    return f"background process {process.pid}"


def healthcheck(port: int, timeout: float = 3.0) -> bool:
    try:
        url = f"http://127.0.0.1:{port}/healthz"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def setup(
    *,
    key_stdin: bool,
    no_validate: bool,
    no_systemd: bool,
    model: str,
    port: int,
) -> None:
    muse = muse_executable()
    if muse is None:
        raise RuntimeError("Muse Code is not installed; install it from https://dev.meta.ai first")
    key = (
        sys.stdin.readline().strip()
        if key_stdin
        else getpass.getpass("OpenRouter API key: ").strip()
    )
    if not KEY_PATTERN.fullmatch(key):
        raise RuntimeError("the OpenRouter key has an unexpected format")
    if not is_muse_model_id(model):
        raise RuntimeError("model must be an OpenRouter meta/muse* model")
    if not no_validate:
        validate_key(key)
    models = fetch_muse_models(key)
    available_ids = {item["id"] for item in models}
    if model not in available_ids:
        raise RuntimeError(f"OpenRouter model is not available: {model}")
    credential = write_credential(key)
    settings = write_muse_settings(model, port)
    service = start_service(model, port, use_systemd=not no_systemd)
    for _ in range(50):
        if healthcheck(port):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("the OpenRouter adapter did not become healthy")
    print(f"OpenRouter credential installed: {credential} (mode 0600)")
    print(f"Muse Code configured: {settings}")
    print(f"Adapter started via {service}")
    print(f"Model: {model}")
    print(f"Available Meta Muse models: {len(models)}")
    print("Run Muse Code normally with: muse")


def list_models(*, selected_model: str | None = None) -> int:
    """Print the live OpenRouter Meta Muse catalog using the stored credential."""
    if selected_model is None:
        try:
            settings = json.loads(muse_settings_path().read_text(encoding="utf-8"))
            configured = settings.get("model")
            selected_model = configured if is_muse_model_id(configured) else None
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    key = read_credential()
    models = fetch_muse_models(key)
    for metadata in models:
        model = metadata["id"]
        marker = "*" if model == selected_model else " "
        print(f"{marker} {model}\t{metadata.get('name') or model}")
    return 0


def doctor(*, port: int, model: str | None, live: bool) -> int:
    failures: list[str] = []
    key = ""
    checked_model = model
    try:
        mode = stat.S_IMODE(credential_path().stat().st_mode)
        if mode != 0o600:
            failures.append(f"credential permissions are {oct(mode)}, expected 0o600")
        key = read_credential()
        validate_key(key)
        print("OpenRouter credential: valid")
    except (OSError, RuntimeError) as exc:
        failures.append(str(exc))
    if healthcheck(port):
        print("Muse Code adapter: healthy")
    else:
        failures.append(f"adapter is not reachable on port {port}")
    try:
        settings = json.loads(muse_settings_path().read_text(encoding="utf-8"))
        expected = f"http://127.0.0.1:{port}/v1"
        configured_model = settings.get("model")
        if not is_muse_model_id(configured_model):
            failures.append("Muse Code model is not a meta/muse* model")
        checked_model = checked_model or configured_model
        if not is_muse_model_id(checked_model):
            failures.append("requested diagnostic model is not a meta/muse* model")
        if (settings.get("endpoint_transport") or {}).get("base_url") != expected:
            failures.append("Muse Code endpoint setting does not match")
        if not failures:
            print(f"Muse Code settings: {muse_settings_path()}")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        failures.append(f"Muse Code settings are unavailable: {exc}")

    if live and not failures and checked_model is not None:
        muse = muse_executable()
        if muse is None:
            failures.append("Muse Code executable not found")
        else:
            env = os.environ.copy()
            env["MUSE_NO_AUTO_UPDATE"] = "1"
            result = subprocess.run(
                [
                    muse,
                    "exec",
                    "--model",
                    checked_model,
                    "--no-session-log",
                    "--disable-write",
                    "--disable-shell",
                    "--disable-web-tools",
                    "--max-model-steps",
                    "1",
                    "Reply with exactly MUSE_OPENROUTER_OK",
                ],
                text=True,
                capture_output=True,
                timeout=180,
                env=env,
            )
            if result.returncode == 0 and "MUSE_OPENROUTER_OK" in result.stdout:
                print("Live Muse Code request through OpenRouter: accepted")
            else:
                failures.append("live Muse Code request through OpenRouter failed")
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    return 0
