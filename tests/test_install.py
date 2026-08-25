import stat

from muse_code_openrouter.install import credential_path, patch_settings_document, write_credential

MODEL = "meta/muse-spark-1.2"
METADATA = {
    "id": MODEL,
    "name": "Meta: Muse Spark 1.2",
    "context_length": 1_048_576,
    "top_provider": {"max_completion_tokens": 65_536},
}


def test_settings_preserve_unrelated_preferences() -> None:
    result = patch_settings_document(
        {"schema_version": 1, "theme": "dark", "voice_enabled": False},
        model=MODEL,
        port=8817,
        metadata=METADATA,
    )
    assert result["theme"] == "dark"
    assert result["voice_enabled"] is False
    assert result["model"] == MODEL
    assert result["endpoint_transport"] == {
        "base_url": "http://127.0.0.1:8817/v1",
        "auth": "none",
    }
    assert result["model_catalog"][0]["profile_id"] == "tbh"


def test_credential_written_privately(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    key = "sk-or-v1-" + "a" * 64
    path = write_credential(key)
    assert path == credential_path()
    assert path.read_text().strip() == key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
