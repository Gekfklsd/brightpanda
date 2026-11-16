"""The bot through the template's real question loop, with fake models, fake research and a
fake Metaculus. Nothing here touches the network."""

import asyncio
import itertools
import json

import pytest

from forecasting_tools import (
    BinaryQuestion,
    MultipleChoiceQuestion,
    PredictedOption,
    PredictedOptionList,
    ReasonedPrediction,
)

import main
from panda import bot as B
from panda import research, runlog

REASONING = ("(b) base rate 20%...\nKEY: Base rate about 20% for similar votes; the partner said on 12 Nov it will abstain.\n"
             "SOURCES: Reuters, Politico Europe\nProbability: 25%")
GOOD = ("Started from a 20% base rate for similar votes. Reuters reported on 12 Nov that the coalition "
        "partner will abstain, which kept the number low. Sources: Reuters, Politico Europe.")


class FakeLlm:
    def __init__(self, text=GOOD, fail=False):
        self.text, self.fail, self.prompts = text, fail, []

    async def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("model down")
        return self.text


class FakeMetaculus:
    def __init__(self):
        self.predictions, self.comments = [], []

    def post_binary_question_prediction(self, question_id, prediction_in_decimal):
        self.predictions.append((question_id, prediction_in_decimal))

    def post_multiple_choice_question_prediction(self, question_id, options_with_probabilities):
        self.predictions.append((question_id, options_with_probabilities))

    def post_question_comment(self, post_id, comment_text, is_private=True, included_forecast=True):
        self.comments.append(dict(post_id=post_id, text=comment_text, is_private=is_private))


def binary_q(i=1):
    return BinaryQuestion(question_text=f"Will the government fall by 2027? ({i})", id_of_question=i, id_of_post=100 + i,
                          page_url=f"https://www.metaculus.com/questions/{100 + i}/", resolution_criteria="Resolves yes if...",
                          fine_print="", background_info="")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(runlog, "STATE", tmp_path / "state")
    monkeypatch.delenv("PANDA_LOG_PUBKEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def fake_gather(question, budget):
        return research.Research(text="News: the partner will abstain (Reuters, 12 Nov).", sources=["Reuters"],
                                 asknews_calls=6, used=["asknews", "web"])

    monkeypatch.setattr(research, "gather", fake_gather)
    values = itertools.cycle([0.0, 0.2, 0.3, 0.99, 0.25])

    async def fake_binary(self, question, prompt):
        assert "outside view" in prompt.lower() or "Outside view" in prompt
        assert "KEY:" in prompt and "SOURCES:" in prompt
        assert question.resolution_criteria in prompt
        return ReasonedPrediction(prediction_value=next(values), reasoning=REASONING)

    monkeypatch.setattr(main.FallTemplateBot2026, "_binary_prompt_to_forecast", fake_binary)
    return tmp_path


def make(publish, comment_llm, client=None):
    return B.BrightPandaBot(
        research_reports_per_question=1, predictions_per_research_report=5, use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=publish, folder_to_save_reports_to=None, skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=False, llms=B.BrightPandaBot.panda_llms(), budget=runlog.load_budget(),
        comment_llm=comment_llm, metaculus_client=client or FakeMetaculus(),
    )


def log_rows(tmp):
    return [json.loads(l) for l in (tmp / "logs" / "local.jsonl").read_text().splitlines()]


def test_median_of_guarded_runs_is_sent_with_a_private_short_comment(env):
    client = FakeMetaculus()
    bot = make(True, FakeLlm(), client)
    [report] = asyncio.run(bot.forecast_questions([binary_q()], return_exceptions=True))
    assert not isinstance(report, BaseException), report
    # runs 0.0 0.2 0.3 0.99 0.25 are guarded to 0.03 .. 0.97, median 0.25
    assert report.prediction == pytest.approx(0.25)
    assert client.predictions == [(1, pytest.approx(0.25))]
    [c] = client.comments
    assert c["is_private"] is True
    assert len(c["text"]) <= 500
    assert c["text"].startswith("# BrightPanda forecast: 25.0%")
    assert "Reuters" in c["text"]
    [row] = log_rows(env)
    assert row["ok"] and row["published"] and row["forecast"] == "25.0%"
    assert row["sources"] == ["Reuters"] and row["asknews_calls"] == 6
    assert bot.budget["sent"] == 1 and bot.budget["asknews_season"] == 6


def test_comment_model_down_falls_back_to_key_lines(env):
    client = FakeMetaculus()
    [report] = asyncio.run(make(True, FakeLlm(fail=True), client).forecast_questions([binary_q()], return_exceptions=True))
    assert not isinstance(report, BaseException), report
    assert "partner said on 12 Nov" in client.comments[0]["text"]


def test_no_good_comment_means_nothing_sent(env, monkeypatch):
    monkeypatch.setattr(B.C, "fallback_body", lambda r: "")
    client = FakeMetaculus()
    [report] = asyncio.run(make(True, FakeLlm(text="Unclear."), client).forecast_questions([binary_q()], return_exceptions=True))
    assert isinstance(report, BaseException)
    assert client.predictions == [] and client.comments == []
    [row] = log_rows(env)
    assert row["ok"] is False and "comment" in row["error"]


def test_dry_run_sends_nothing(env):
    client = FakeMetaculus()
    [report] = asyncio.run(make(False, FakeLlm(), client).forecast_questions([binary_q()], return_exceptions=True))
    assert not isinstance(report, BaseException)
    assert client.predictions == [] and client.comments == []
    assert log_rows(env)[0]["published"] is False


def test_multiple_choice_options_floored(env, monkeypatch):
    async def fake_mc(self, question, prompt):
        assert "KEY:" in prompt and "outside view" in prompt
        return ReasonedPrediction(
            prediction_value=PredictedOptionList(predicted_options=[
                PredictedOption(option_name="A", probability=0.95),
                PredictedOption(option_name="B", probability=0.05),
                PredictedOption(option_name="C", probability=0.0)]),
            reasoning=REASONING)

    monkeypatch.setattr(main.FallTemplateBot2026, "_multiple_choice_prompt_to_forecast", fake_mc)
    q = MultipleChoiceQuestion(question_text="Who wins?", id_of_question=7, id_of_post=107, page_url="u7",
                               options=["A", "B", "C"], resolution_criteria="...", fine_print="", background_info="")
    [report] = asyncio.run(make(False, FakeLlm()).forecast_questions([q], return_exceptions=True))
    assert not isinstance(report, BaseException), report
    probs = {o.option_name: o.probability for o in report.prediction.predicted_options}
    assert min(probs.values()) >= 0.0099 and abs(sum(probs.values()) - 1) < 1e-6


def test_key_never_in_log(env, monkeypatch):
    monkeypatch.setenv("METACULUS_TOKEN", "SECRET-TOKEN-123")
    asyncio.run(make(False, FakeLlm()).forecast_questions([binary_q()], return_exceptions=True))
    assert "SECRET-TOKEN-123" not in (env / "logs" / "local.jsonl").read_text()
