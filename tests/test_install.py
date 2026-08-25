import stat

from muse_code_openrouter.install import (
    CONTRIBUTOR_DISCLOSURE,
    choose_muse_model,
    credential_path,
    is_contributor_model_id,
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
        models=[METADATA, CONTRIBUTOR],
    )
    assert result["theme"] == "dark"
    assert result["voice_enabled"] is False
    assert result["model"] == MODEL
    assert result["endpoint_transport"] == {
        "base_url": "http://127.0.0.1:8817/v1",
        "auth": "none",
    }
    rows = result["model_catalog"]
    assert [row["model_id"] for row in rows] == [MODEL, CONTRIBUTOR["id"]]
    assert all(row["visibility"] == "visible" for row in rows)
    assert rows[0]["output_limit"] == 16_384
    assert rows[1]["display_label"].startswith("WARNING:")
    assert CONTRIBUTOR_DISCLOSURE in rows[1]["description"]


def test_settings_replace_old_static_model_catalog() -> None:
    result = patch_settings_document(
        {"model_catalog": [{"model_id": "old"}]},
        model=MODEL,
        port=8817,
        models=[METADATA, CONTRIBUTOR],
    )
    assert [row["model_id"] for row in result["model_catalog"]] == [
        MODEL,
        CONTRIBUTOR["id"],
    ]


def test_model_boundary_accepts_only_meta_muse_models() -> None:
    assert is_muse_model_id("meta/muse-spark-1.2")
    assert is_muse_model_id("meta/muse-spark-1.2-contributor")
    assert is_muse_model_id("meta/muse-glimmer-30b")
    assert not is_muse_model_id("openai/gpt-5")
    assert not is_muse_model_id("meta/llama-4")
    assert not is_muse_model_id("meta/muse/../../other")
    assert is_contributor_model_id("meta/muse-spark-1.2-contributor")
    assert is_contributor_model_id("meta/muse-future-CONTRIBUTOR-preview")
    assert not is_contributor_model_id("meta/muse-spark-1.2")


def test_interactive_chooser_warns_for_contributor(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    selected = choose_muse_model([METADATA, CONTRIBUTOR], MODEL)
    assert selected == CONTRIBUTOR["id"]
    captured = capsys.readouterr()
    assert "Contributor: data-use warning" in captured.out
    assert CONTRIBUTOR_DISCLOSURE in captured.err


def test_credential_written_privately(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    key = "sk-or-v1-" + "a" * 64
    path = write_credential(key)
    assert path == credential_path()
    assert path.read_text().strip() == key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
