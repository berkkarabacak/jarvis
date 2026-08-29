"""ORCH-362: OpenRouter leaderboard snapshot + live parse (no spend)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.jarvis.model_router import _DEFAULT_LADDER
from app.jarvis.openrouter_leaders import (
    DEFAULT_TOP_N,
    SNAPSHOT_MODEL_IDS,
    cheap_catalog_ids,
    cost_sorted_model_ids,
    fetch_live_leaders,
    helper_models_public,
    is_allowed_helper_model,
    load_leaders,
    pad_with_snapshot,
    parse_models_catalog,
    parse_weekly_rankings,
    reset_leaders_cache_for_tests,
    resolve_ranked_slug,
    smart_catalog_ids,
    snapshot_leaders,
)
from app.jarvis.settings_store import _DEFAULT_MODEL_SUGGESTIONS

HIGH_IQ_SNAPSHOT = tuple(m.model for m in snapshot_leaders() if m.is_high_iq)
USAGE_RANK_ONE = "deepseek/deepseek-v4-flash-0731"
FREE_SNAPSHOT = tuple(m.model for m in snapshot_leaders() if m.is_free)
from app.llm.openrouter import DEFAULT_OPENROUTER_MODELS


INVENTED_SLUGS = (
    "deepseek/deepseek-v4-flash-0423",
    "deepseek/deepseek-v4-flash-0731-pro",
    "tencent/hy3-pro",
    "openai/gpt-5.6-flash",
    "xiaomi/mimo-v2.5-free",
    "z-ai/glm-5.2-flash",
    "z-ai/glm-5.3",
    "nvidia/nemotron-3-ultra-free",
    "google/gemini-3.6-flash-free",
    "poolside/laguna-s-2.1-free",
)

PROD_FILES = (
    Path("app/jarvis/openrouter_leaders.py"),
    Path("app/jarvis/model_router.py"),
    Path("app/llm/openrouter.py"),
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_leaders_cache_for_tests()
    yield
    reset_leaders_cache_for_tests()


def test_snapshot_ids_are_real_openrouter_slugs():
    assert DEFAULT_TOP_N == 20
    assert len(SNAPSHOT_MODEL_IDS) == 20
    assert len(set(SNAPSHOT_MODEL_IDS)) == 20
    assert SNAPSHOT_MODEL_IDS[0] == "deepseek/deepseek-v4-flash-0731"
    assert "tencent/hy3" in SNAPSHOT_MODEL_IDS
    assert "openai/gpt-5.6-luna" in SNAPSHOT_MODEL_IDS
    assert "deepseek/deepseek-v4-flash" in SNAPSHOT_MODEL_IDS
    assert "deepseek/deepseek-v4-pro-0813" in SNAPSHOT_MODEL_IDS
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in SNAPSHOT_MODEL_IDS
    for mid in SNAPSHOT_MODEL_IDS:
        assert "/" in mid
        vendor, rest = mid.split("/", 1)
        assert vendor and rest
        assert " " not in mid
        assert "gpt-realtime" not in mid


def test_catalog_includes_snapshot_ids():
    for mid in SNAPSHOT_MODEL_IDS:
        assert mid in DEFAULT_OPENROUTER_MODELS


def test_snapshot_uses_current_v4_pro_ga_not_0423_or_glm_53():
    assert "deepseek/deepseek-v4-pro-0813" in SNAPSHOT_MODEL_IDS
    assert "deepseek/deepseek-v4-pro" in SNAPSHOT_MODEL_IDS
    assert SNAPSHOT_MODEL_IDS.index("deepseek/deepseek-v4-pro") != SNAPSHOT_MODEL_IDS.index(
        "deepseek/deepseek-v4-pro-0813"
    )
    assert "z-ai/glm-5.2" in SNAPSHOT_MODEL_IDS
    assert "z-ai/glm-5.3" not in SNAPSHOT_MODEL_IDS


def test_default_ladder_and_suggestions_use_current_catalog_ids():
    assert "deepseek/deepseek-v4-pro-0813" in _DEFAULT_LADDER
    assert "z-ai/glm-5.2" in _DEFAULT_LADDER
    assert "deepseek/deepseek-v4-flash-0731" in _DEFAULT_LADDER
    assert all("gpt-4.1" not in mid for mid in _DEFAULT_LADDER)
    assert "deepseek/deepseek-v4-pro-0813" in _DEFAULT_MODEL_SUGGESTIONS
    assert "z-ai/glm-5.2" in _DEFAULT_MODEL_SUGGESTIONS
    assert "z-ai/glm-5.3" not in _DEFAULT_MODEL_SUGGESTIONS
    assert all("gpt-4.1" not in mid for mid in _DEFAULT_MODEL_SUGGESTIONS)


def test_production_code_has_no_invented_model_ids():
    blob = "\n".join(p.read_text(encoding="utf-8") for p in PROD_FILES)
    for bad in INVENTED_SLUGS:
        assert f'"{bad}"' not in blob
        assert f"'{bad}'" not in blob
    for mid in SNAPSHOT_MODEL_IDS:
        assert f'"{mid}"' in blob or f"'{mid}'" in blob


def test_cost_sort_puts_one_free_then_cheap_paid():
    ordered = cost_sorted_model_ids(snapshot_leaders())
    assert ordered[0] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert ordered[1] == "deepseek/deepseek-v4-flash"
    assert "poolside/laguna-s-2.1:free" in ordered
    assert ordered.index("poolside/laguna-s-2.1:free") > ordered.index(
        "deepseek/deepseek-v4-flash"
    )


def test_smart_catalog_is_paid_high_iq_not_usage_rank():
    leaders = snapshot_leaders()
    smart = smart_catalog_ids(leaders)
    by_id = {m.model: m for m in leaders}
    assert smart[0] != USAGE_RANK_ONE
    assert USAGE_RANK_ONE not in smart[:1]
    for mid in FREE_SNAPSHOT:
        assert mid not in smart
    for mid in HIGH_IQ_SNAPSHOT:
        assert mid in smart
    assert by_id[USAGE_RANK_ONE].rank == 1
    assert by_id[smart[0]].rank != 1
    assert by_id[smart[0]].is_high_iq is True
    assert all(by_id[mid].is_high_iq for mid in smart)
    assert by_id[USAGE_RANK_ONE].is_high_iq is False
    assert by_id[FREE_SNAPSHOT[0]].is_high_iq is False


def test_cheap_catalog_paid_skips_free_tip():
    paid = cheap_catalog_ids(snapshot_leaders(), allow_free=False)
    assert paid[0] == "deepseek/deepseek-v4-flash"
    assert not paid[0].endswith(":free")
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in paid
    assert paid.index("nvidia/nemotron-3-ultra-550b-a55b:free") > 0


def test_resolve_ranked_slug_maps_canonical_and_skips_unknown():
    catalog = parse_models_catalog(
        {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash-0731",
                    "canonical_slug": "deepseek/deepseek-v4-flash-20260731",
                },
                {
                    "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                    "canonical_slug": "nvidia/nemotron-3-ultra-550b-a55b-20260604",
                },
                {
                    "id": "openai/gpt-5.6-luna:batch",
                    "canonical_slug": "openai/gpt-5.6-luna-20260709",
                },
            ]
        }
    )
    assert "openai/gpt-5.6-luna:batch" not in catalog
    assert (
        resolve_ranked_slug("deepseek/deepseek-v4-flash-20260731", catalog)
        == "deepseek/deepseek-v4-flash-0731"
    )
    assert (
        resolve_ranked_slug("nvidia/nemotron-3-ultra-550b-a55b:free", catalog)
        == "nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    assert resolve_ranked_slug("invented/not-a-real-model", catalog) is None
    assert resolve_ranked_slug("other", catalog) is None


def test_parse_weekly_rankings_drops_unknown_and_other():
    catalog = parse_models_catalog(
        {
            "data": [
                {
                    "id": "tencent/hy3",
                    "canonical_slug": "tencent/hy3-20260706",
                    "pricing": {"prompt": "0.000000132", "completion": "0.000000528"},
                    "supported_parameters": ["tools"],
                }
            ]
        }
    )
    models, as_of = parse_weekly_rankings(
        {
            "data": [
                {
                    "date": "2026-08-10",
                    "model_permaslug": "invented/nope",
                    "total_tokens": "999",
                },
                {
                    "date": "2026-08-10",
                    "model_permaslug": "tencent/hy3",
                    "total_tokens": "10",
                },
                {
                    "date": "2026-08-10",
                    "model_permaslug": "other",
                    "total_tokens": "1",
                },
            ],
            "meta": {"as_of": "2026-08-11T00:00:00Z"},
        },
        catalog,
    )
    assert [m.model for m in models] == ["tencent/hy3"]
    assert as_of == "2026-08-11T00:00:00Z"


def test_load_leaders_falls_back_when_live_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "1")

    def boom(url: str, headers: dict, timeout: float) -> dict:
        raise RuntimeError("no network")

    monkeypatch.setattr("app.jarvis.openrouter_leaders._http_get_json", boom)
    result = load_leaders()
    assert result.source == "snapshot"
    assert result.ids == SNAPSHOT_MODEL_IDS
    assert result.error


def test_fetch_live_leaders_uses_catalog_ids_only():
    def fake_get(url: str, headers: dict, timeout: float) -> dict:
        if "rankings-daily" in url:
            return {
                "data": [
                    {
                        "date": "2026-08-10",
                        "model_permaslug": "openai/gpt-5.6-luna-20260709",
                        "total_tokens": "5",
                    }
                ],
                "meta": {"as_of": "2026-08-14T12:00:00Z"},
            }
        return {
            "data": [
                {
                    "id": "openai/gpt-5.6-luna",
                    "canonical_slug": "openai/gpt-5.6-luna-20260709",
                    "name": "OpenAI: GPT-5.6 Luna",
                    "pricing": {"prompt": "0.0000001", "completion": "0.0000006"},
                    "supported_parameters": ["tools"],
                }
            ]
        }

    result = fetch_live_leaders(getter=fake_get, api_key="sk-test")
    assert result.source == "live"
    assert result.ids == ("openai/gpt-5.6-luna",)


def test_helper_models_public_are_catalog_ids_without_realtime(monkeypatch):
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    helpers = helper_models_public()
    assert 1 <= len(helpers) <= 20
    ids = [row["id"] for row in helpers]
    assert len(ids) == len(set(ids))
    for row in helpers:
        assert row["id"] in SNAPSHOT_MODEL_IDS
        assert row["name"]
        assert "gpt-realtime" not in row["id"]
        assert "sk-" not in row["id"]
        assert "OPENROUTER" not in str(row)
        assert "price" not in row
    assert is_allowed_helper_model(SNAPSHOT_MODEL_IDS[0]) is True
    assert is_allowed_helper_model("gpt-realtime") is False
    assert is_allowed_helper_model("invented/not-a-real-model") is False


def test_pad_with_snapshot_uses_known_rows_only():
    one = snapshot_leaders()[:1]
    padded = pad_with_snapshot(one)
    assert len(padded) == 20
    assert padded[0].model == one[0].model
    assert {m.model for m in padded} <= set(SNAPSHOT_MODEL_IDS)
    assert "gpt-realtime" not in {m.model for m in padded}
