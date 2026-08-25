from muse_code_openrouter.rewrite import (
    alias_tool_name,
    collect_encrypted_replay_ids,
    filter_encrypted_replay_items,
    restore_response,
    rewrite_request,
)


def test_long_tool_name_round_trip() -> None:
    original = "tool_" + "x" * 80
    payload = {"tools": [{"type": "function", "name": original}]}
    rewritten, aliases = rewrite_request(payload)
    alias = rewritten["tools"][0]["name"]
    assert len(alias) <= 64
    assert aliases[alias] == original
    assert restore_response({"name": alias}, aliases)["name"] == original


def test_short_tool_name_is_unchanged() -> None:
    payload = {"tools": [{"type": "function", "name": "read_file"}]}
    assert rewrite_request(payload) == (payload, {})


def test_alias_is_deterministic() -> None:
    name = "x" * 100
    assert alias_tool_name(name) == alias_tool_name(name)


def test_filter_removes_only_blocked_encrypted_replay_items() -> None:
    stale = {"type": "reasoning", "encrypted_content": "spark-state", "summary": []}
    current = {"type": "compaction", "encrypted_content": "glimmer-state"}
    ordinary = {"role": "user", "content": "keep this"}
    payload = {"input": [ordinary, stale, current], "tools": [{"name": "read_file"}]}
    stale_ids = collect_encrypted_replay_ids(stale)

    filtered, removed = filter_encrypted_replay_items(payload, stale_ids)

    assert removed == 1
    assert filtered["input"] == [ordinary, current]
    assert filtered["tools"] == payload["tools"]
    assert "spark-state" not in repr(stale_ids)


def test_collect_encrypted_replay_ids_ignores_unencrypted_reasoning() -> None:
    payload = {
        "input": [
            {"type": "reasoning", "summary": [{"text": "visible"}]},
            {"type": "message", "encrypted_content": "not-model-state"},
            {"type": ["text"], "encrypted_content": "schema-type-list"},
        ]
    }
    assert collect_encrypted_replay_ids(payload) == set()
