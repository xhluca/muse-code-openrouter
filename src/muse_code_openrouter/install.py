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
CATALOG_OUTPUT_LIMIT = 16_384
CONTRIBUTOR_DISCLOSURE = (
    "Your prompts and outputs may be used to improve Meta's products."
)
CONTRIBUTOR_INFO_URL = "https://openrouter.ai/meta/muse-spark-1.2-contributor"
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


def is_contributor_model_id(model: Any) -> bool:
    """Return whether a model id carries the Contributor data-use tier marker."""
    return isinstance(model, str) and "contributor" in model.lower()


def contributor_warning(model: str) -> str:
    """Return the official-disclosure-based warning for a Contributor model."""
    return (
        f"WARNING: {model} is a Contributor model. {CONTRIBUTOR_DISCLOSURE} "
        f"Only continue if you accept this data use. Details: {CONTRIBUTOR_INFO_URL}"
    )


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
    reported_output = _positive_int(
        provider.get("max_completion_tokens") if isinstance(provider, dict) else None,
        CATALOG_OUTPUT_LIMIT,
    )
    output = min(reported_output, CATALOG_OUTPUT_LIMIT, context)
    contributor = is_contributor_model_id(model)
    label = metadata.get("name") or model
    description = "Served through OpenRouter"
    if contributor:
        label = f"WARNING: {label} (Contributor data use)"
        description = f"WARNING: {CONTRIBUTOR_DISCLOSURE} {CONTRIBUTOR_INFO_URL}"
    return {
        "model_id": model,
        "provider_id": "meta",
        "profile_id": "tbh",
        "display_label": label,
        "visibility": "visible",
        "display_order": display_order,
        "is_default": model == selected_model,
        "context_limit": context,
        "output_limit": min(output, context),
        "description": description,
    }


def choose_muse_model(models: list[dict[str, Any]], default_model: str) -> str:
    """Prompt for a default from the already-fetched live Muse model catalog."""
    ids = [metadata["id"] for metadata in models]
    default_index = ids.index(default_model) if default_model in ids else 0
    print("Choose the default Meta Muse model:")
    for index, metadata in enumerate(models, 1):
        model = metadata["id"]
        suffix = " [Contributor: data-use warning]" if is_contributor_model_id(model) else ""
        default = " [default]" if index - 1 == default_index else ""
        print(f"  {index}) {model}{suffix}{default}")
    while True:
        answer = input(f"Model [1-{len(models)}] (default {default_index + 1}): ").strip()
        if not answer:
            selected = ids[default_index]
            break
        try:
            selected = ids[int(answer) - 1]
            break
        except (ValueError, IndexError):
            print(f"Enter a number from 1 to {len(models)}.", file=sys.stderr)
    if is_contributor_model_id(selected):
        print(contributor_warning(selected), file=sys.stderr)
    return selected


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def patch_settings_document(
    existing: dict[str, Any], *, model: str, port: int, models: list[dict[str, Any]]
) -> dict[str, Any]:
    updated = dict(existing)
    updated.setdefault("schema_version", 1)
    updated["provider"] = "meta"
    updated["model"] = model
    updated["endpoint_transport"] = {
        "base_url": f"http://127.0.0.1:{port}/v1",
        "auth": "none",
    }
    updated["model_catalog"] = [
        model_catalog_row(metadata, selected_model=model, display_order=index)
        for index, metadata in enumerate(models)
    ]
    return updated


def write_muse_settings(model: str, port: int, models: list[dict[str, Any]]) -> Path:
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

    updated = patch_settings_document(existing, model=model, port=port, models=models)
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
    choose_model: bool,
    model: str,
    port: int,
) -> None:
    muse = muse_executable()
    if muse is None:
        raise RuntimeError("Muse Code is not installed; install it from https://dev.meta.ai first")
    if key_stdin and choose_model:
        raise RuntimeError("--choose-model cannot be combined with --key-stdin")
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
    if choose_model:
        model = choose_muse_model(models, model)
    if model not in available_ids:
        raise RuntimeError(f"OpenRouter model is not available: {model}")
    if is_contributor_model_id(model) and not choose_model:
        print(contributor_warning(model), file=sys.stderr)
    credential = write_credential(key)
    settings = write_muse_settings(model, port, models)
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
        warning = (
            "\tWARNING: Contributor data-use terms apply"
            if is_contributor_model_id(model)
            else ""
        )
        print(f"{marker} {model}\t{metadata.get('name') or model}{warning}")
    contributor_models = [item["id"] for item in models if is_contributor_model_id(item["id"])]
    if contributor_models:
        print(
            f"WARNING for *contributor* models: {CONTRIBUTOR_DISCLOSURE} "
            f"Details: {CONTRIBUTOR_INFO_URL}",
            file=sys.stderr,
        )
    return 0


def select_default_model(*, model: str | None, port: int, no_systemd: bool) -> int:
    """Select a default using the stored key and refresh Muse's visible catalog."""
    key = read_credential()
    models = fetch_muse_models(key)
    current_model: str = DEFAULT_MODEL
    try:
        settings = json.loads(muse_settings_path().read_text(encoding="utf-8"))
        configured = settings.get("model")
        if is_muse_model_id(configured):
            current_model = configured
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    selected = model or choose_muse_model(models, current_model)
    available_ids = {item["id"] for item in models}
    if selected not in available_ids:
        raise RuntimeError(f"OpenRouter model is not available: {selected}")
    if is_contributor_model_id(selected) and model is not None:
        print(contributor_warning(selected), file=sys.stderr)
    settings_path = write_muse_settings(selected, port, models)
    service = start_service(selected, port, use_systemd=not no_systemd)
    for _ in range(50):
        if healthcheck(port):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("the OpenRouter adapter did not become healthy")
    print(f"Muse Code default model: {selected}")
    print(f"Visible catalog refreshed: {settings_path} ({len(models)} models)")
    print(f"Adapter restarted via {service}")
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
        visible_models = {
            row.get("model_id")
            for row in settings.get("model_catalog", [])
            if isinstance(row, dict)
            and row.get("visibility") == "visible"
            and row.get("provider_id") == "meta"
            and row.get("profile_id") == "tbh"
        }
        if not visible_models:
            failures.append("Muse Code model catalog has no visible models")
        elif checked_model not in visible_models:
            failures.append("requested diagnostic model is not visible in Muse Code's catalog")
        if not failures:
            print(f"Muse Code settings: {muse_settings_path()}")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        failures.append(f"Muse Code settings are unavailable: {exc}")

    if live and not failures and checked_model is not None:
        if is_contributor_model_id(checked_model):
            print(contributor_warning(checked_model), file=sys.stderr)
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
