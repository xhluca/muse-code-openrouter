import json

import pytest

from muse_code_openrouter.proxy import rewrite_sse_block, translate_catalog


def test_catalog_translation_for_selected_model() -> None:
    payload = {
        "data": [
            {"id": "other/model", "name": "Other", "context_length": 10},
            {
                "id": "meta/muse-spark-1.2",
                "name": "Meta: Muse Spark 1.2",
                "context_length": 1_048_576,
                "top_provider": {"max_completion_tokens": 65_536},
            },
        ]
    }
    row = translate_catalog(payload, "meta/muse-spark-1.2")["data"][0]
    assert row["model_id"] == "meta/muse-spark-1.2"
    assert row["provider_id"] == "meta"
    assert row["profile_id"] == "tbh"
    assert row["is_default"] is True
    assert row["context_limit"] == 1_048_576


def test_catalog_rejects_missing_model() -> None:
    with pytest.raises(ValueError, match="not available"):
        translate_catalog({"data": []}, "meta/muse-spark-1.2")


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
