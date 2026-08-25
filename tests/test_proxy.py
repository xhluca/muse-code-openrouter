import json

import pytest

from muse_code_openrouter.proxy import (
    enforce_output_limit,
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
    rows = translate_catalog(payload, "meta/muse-spark-1.2")["data"]
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
