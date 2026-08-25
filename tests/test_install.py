import json
import shutil
import stat

from muse_code_openrouter.install import (
    CONTRIBUTOR_DISCLOSURE,
    choose_muse_model,
    credential_path,
    is_contributor_model_id,
    is_muse_model_id,
    patch_settings_document,
    restore_muse_settings,
    state_dir,
    uninstall,
    write_credential,
    write_systemd_unit,
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


def test_restore_removes_settings_that_were_absent_before_setup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = tmp_path / "config" / "muse" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            patch_settings_document({}, model=MODEL, port=8817, models=[METADATA])
        )
    )
    marker = state_dir() / "settings.was-absent"
    marker.parent.mkdir(parents=True)
    marker.write_text("\n")

    result = restore_muse_settings()

    assert "did not exist before setup" in result
    assert not settings.exists()


def test_restore_preserves_later_unrelated_preferences(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = tmp_path / "config" / "muse" / "settings.json"
    settings.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "provider": "meta",
        "model": "meta/muse-spark-1.1",
        "theme": "light",
    }
    current = patch_settings_document(
        original, model=MODEL, port=8817, models=[METADATA, CONTRIBUTOR]
    )
    current["theme"] = "dark"
    current["voice_enabled"] = False
    settings.write_text(json.dumps(current))
    backup = state_dir() / "settings.before-openrouter.json"
    backup.parent.mkdir(parents=True)
    backup.write_text(json.dumps(original))

    restore_muse_settings()

    restored = json.loads(settings.read_text())
    assert restored["provider"] == original["provider"]
    assert restored["model"] == original["model"]
    assert "endpoint_transport" not in restored
    assert "model_catalog" not in restored
    assert restored["theme"] == "dark"
    assert restored["voice_enabled"] is False
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600


def test_restore_preserves_non_openrouter_transport_and_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = tmp_path / "config" / "muse" / "settings.json"
    settings.parent.mkdir(parents=True)
    current = {
        "schema_version": 1,
        "provider": "echo",
        "model": "custom/model",
        "endpoint_transport": {"base_url": "https://example.test/v1", "auth": "bearer"},
    }
    settings.write_text(json.dumps(current))
    marker = state_dir() / "settings.was-absent"
    marker.parent.mkdir(parents=True)
    marker.write_text("\n")

    restore_muse_settings()

    assert json.loads(settings.read_text()) == current


def test_uninstall_cleans_isolated_install(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    settings = tmp_path / "config" / "muse" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            patch_settings_document({}, model=MODEL, port=8817, models=[METADATA])
        )
    )
    marker = state_dir() / "settings.was-absent"
    marker.parent.mkdir(parents=True)
    marker.write_text("\n")
    credential = write_credential("sk-or-v1-" + "a" * 64)
    unit = write_systemd_unit(MODEL, 8817)
    real_which = shutil.which
    monkeypatch.setattr(
        "muse_code_openrouter.install.shutil.which",
        lambda command: "/bin/true" if command == "systemctl" else real_which(command),
    )

    assert uninstall(remove_package=False) == 0

    assert not settings.exists()
    assert not credential.exists()
    assert not state_dir().exists()
    assert not unit.exists()
    output = capsys.readouterr().out
    assert "integration removed" in output
    assert "--remove-package" in output
