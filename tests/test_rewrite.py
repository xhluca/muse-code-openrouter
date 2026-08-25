from muse_code_openrouter.rewrite import alias_tool_name, restore_response, rewrite_request


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
