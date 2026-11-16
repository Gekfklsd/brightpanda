"""The pure parts: guards, the comment, the AskNews pacing, the log."""

import json
from datetime import datetime, timezone

import pytest

from panda import comment as C
from panda import config, guards, research, runlog


# ---------------------------------------------------------------- guards
def test_binary_clamped_both_ends():
    assert guards.clamp_binary(0.0) == config.BINARY_FLOOR
    assert guards.clamp_binary(1.0) == config.BINARY_CEILING
    assert guards.clamp_binary(0.42) == 0.42


def test_binary_nan_refused():
    with pytest.raises(ValueError):
        guards.clamp_binary(float("nan"))


def test_options_floor_keeps_order_and_sums_to_one():
    out = guards.floor_options({"A": 0.9, "B": 0.1, "C": 0.0})
    assert abs(sum(out.values()) - 1) < 1e-9
    assert min(out.values()) >= config.OPTION_FLOOR - 1e-12
    assert out["A"] > out["B"] > out["C"]


def test_options_untouched_when_already_fine():
    src = {"A": 0.5, "B": 0.3, "C": 0.2}
    assert guards.floor_options(src) == pytest.approx(src)


def test_options_all_zero_go_uniform():
    assert guards.floor_options({"A": 0, "B": 0}) == {"A": 0.5, "B": 0.5}


# --------------------------------------------------------------- comment
GOOD = ("Base rate for incumbents losing a confidence vote is about 10%. Reuters on 12 Nov reported "
        "the coalition partner will abstain, which lifts the odds. Sources: Reuters, Politico Europe.")


def test_comment_fits_and_passes():
    c = C.build("34.0%", GOOD)
    assert len(c) <= 500
    assert c.startswith("# BrightPanda forecast: 34.0%\n")
    assert C.problems(c) == []


def test_long_body_is_cut_under_limit_on_a_sentence():
    c = C.build("34.0%", (GOOD + " ") * 10)
    assert len(c) <= 500
    assert c.endswith(".")
    assert C.problems(c) == []


def test_urls_and_markdown_stripped():
    c = C.build("10%", "**Bold** claim https://example.com/a/very/long/link per Reuters on 3 Nov, base rate 20% from past cases.")
    assert "http" not in c and "**" not in c


def test_thin_or_ai_sounding_comment_refused():
    assert C.problems(C.build("50%", "Unclear."))
    assert C.problems(C.build("50%", "As an AI language model I think the base rate here is around twenty percent overall."))


def test_over_limit_refused():
    assert C.problems("# BrightPanda forecast: 5%\n" + "x" * 600)


def test_fallback_body_reads_key_and_sources():
    r = "blah\nKEY: Base rate 15%; the bill passed committee on 4 Nov.\nSOURCES: AP, Senate.gov\nProbability: 22%"
    assert C.fallback_body(r) == "Base rate 15%; the bill passed committee on 4 Nov. Sources: AP, Senate.gov"


# ---------------------------------------------------------- AskNews pace
def test_full_search_while_under_pace():
    day = datetime(2026, 11, 16, tzinfo=timezone.utc)  # pace ~533 calls
    assert research.asknews_plan(100, 100, day) == research.FULL


def test_latest_only_when_ahead_of_pace():
    day = datetime(2026, 11, 2, tzinfo=timezone.utc)  # pace ~66 calls
    assert research.asknews_plan(64, 64, day) == research.LATEST


def test_none_when_month_spent():
    day = datetime(2026, 11, 30, tzinfo=timezone.utc)
    assert research.asknews_plan(1000, 1000, day) == research.NONE


def test_none_when_season_spent():
    day = datetime(2026, 12, 30, tzinfo=timezone.utc)
    assert research.asknews_plan(0, 4000, day) == research.NONE


# ------------------------------------------------------------------ log
def test_log_in_clear_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PANDA_LOG_PUBKEY", raising=False)
    p = runlog.write({"title": "Q", "forecast": "40%"}, logs=tmp_path)
    assert p.name == "local.jsonl"
    assert json.loads(p.read_text())["forecast"] == "40%"


def test_log_encrypted_and_readable_only_with_private_key(tmp_path, monkeypatch):
    import base64

    import pyrage

    ident = pyrage.x25519.Identity.generate()
    monkeypatch.setenv("PANDA_LOG_PUBKEY", str(ident.to_public()))
    p = runlog.write({"title": "Secret question", "forecast": "40%"}, logs=tmp_path)
    raw = p.read_text()
    assert p.name == "runs.age.jsonl"
    assert "Secret question" not in raw and "40%" not in raw
    blob = base64.b64decode(json.loads(raw)["age"])
    assert json.loads(pyrage.decrypt(blob, [ident]))["forecast"] == "40%"


def test_budget_counts_by_month(tmp_path):
    b = runlog.load_budget(tmp_path)
    runlog.spend_asknews(b, 6)
    runlog.save_budget(b, tmp_path)
    b2 = runlog.load_budget(tmp_path)
    assert b2["asknews_season"] == 6
    assert runlog.asknews_used_this_month(b2) == 6


# ------------------------------------------------- one line forecast
def test_compact_every_type_fits_one_short_line():
    from forecasting_tools import NumericDistribution, NumericQuestion, Percentile, PredictedOption, PredictedOptionList

    assert C.compact(0.25) == "25%"
    many = PredictedOptionList(predicted_options=[
        PredictedOption(option_name=f"A rather long option name number {i}", probability=(i + 1) / 36) for i in range(8)])
    mc = C.compact(many)
    assert "\n" not in mc and len(mc) <= 160 and mc.endswith("more")
    assert mc.startswith("A rather long option name number 7 22%")
    q = NumericQuestion(question_text="How many?", id_of_question=3, id_of_post=3, page_url="u", upper_bound=100,
                        lower_bound=0, open_upper_bound=True, open_lower_bound=False, unit_of_measure="deaths")
    d = NumericDistribution.from_question([Percentile(percentile=p, value=v) for p, v in
                                           [(0.1, 5), (0.2, 8), (0.4, 12), (0.6, 15), (0.8, 20), (0.9, 30)]], q)
    assert C.compact(d) == "median 13.5 (80% between 5 and 30)"
    assert C.compact(d, is_date=True).startswith("median 01 Jan 1970")
    for f in (mc, C.compact(d)):
        assert C.problems(C.build(f, GOOD)) == []


def test_blank_settings_fall_back_to_defaults(monkeypatch):
    # GitHub passes an unset repository variable as an empty string
    import importlib
    for k in ("PANDA_FORECASTER", "PANDA_PARSER", "PANDA_WEB_RESEARCHER", "PANDA_COMMENTER", "PANDA_FORECASTER_EFFORT", "PANDA_RUNS"):
        monkeypatch.setenv(k, "")
    c = importlib.reload(config)
    try:
        assert c.FORECASTER.startswith("openrouter/") and c.PARSER and c.WEB_RESEARCHER and c.COMMENTER
        assert c.RUNS_PER_QUESTION == 5 and c.FORECASTER_EFFORT == "high"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_every_model_call_has_a_word_cap():
    from panda.bot import BrightPandaBot
    for purpose, llm in BrightPandaBot.panda_llms().items():
        if purpose != "researcher":
            assert llm.litellm_kwargs.get("max_tokens"), purpose
