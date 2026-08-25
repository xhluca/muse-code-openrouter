import stat

from muse_code_openrouter.install import (
    credential_path,
    is_muse_model_id,
    patch_settings_document,
    write_credential,
)

MODEL = "meta/muse-spark-1.2"
METADATA = {
    "id": MODEL,
    "name": "Meta: Muse Spark 1.2",
    "context_length": 1_048_576,
    "top_provider": {"max_completion_tokens": 65_536},
}
CONTRIBUTOR = {
    "id": "meta/muse-spark-1.2-contributor",
    "name": "Meta: Muse Spark 1.2 Contributor",
    "context_length": 1_048_576,
    "top_provider": {"max_completion_tokens": 16_384},
}


def test_settings_preserve_unrelated_preferences() -> None:
    result = patch_settings_document(
        {"schema_version": 1, "theme": "dark", "voice_enabled": False},
        model=MODEL,
        port=8817,
    )
    assert result["theme"] == "dark"
    assert result["voice_enabled"] is False
    assert result["model"] == MODEL
    assert result["endpoint_transport"] == {
        "base_url": "http://127.0.0.1:8817/v1",
        "auth": "none",
    }
    assert "model_catalog" not in result


def test_settings_remove_old_static_model_catalog() -> None:
    result = patch_settings_document(
        {"model_catalog": [METADATA, CONTRIBUTOR]}, model=MODEL, port=8817
    )
    assert "model_catalog" not in result


def test_model_boundary_accepts_only_meta_muse_models() -> None:
    assert is_muse_model_id("meta/muse-spark-1.2")
    assert is_muse_model_id("meta/muse-spark-1.2-contributor")
    assert is_muse_model_id("meta/muse-glimmer-30b")
    assert not is_muse_model_id("openai/gpt-5")
    assert not is_muse_model_id("meta/llama-4")
    assert not is_muse_model_id("meta/muse/../../other")


def test_credential_written_privately(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    key = "sk-or-v1-" + "a" * 64
    path = write_credential(key)
    assert path == credential_path()
    assert path.read_text().strip() == key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
