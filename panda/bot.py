"""BrightPandaBot: the official Fall 2026 template bot with our layer on top.

What changes from the template, and why:
- Research: AskNews and a live web search side by side, paced to the free AskNews budget (research.py)
- Binary prompt: outside view first (a reference class and its base rate), then the evidence, then the
  strongest case against, then a calibration check. Written by the prompter role, tested in compare.py
- Every prompt ends with KEY and SOURCES lines so the comment has something real to stand on
- Guards: binary held inside 3% to 97%, every option kept at 1% or more (guards.py)
- Comment: private, under 500 characters, checked before anything is sent (comment.py)
- Log: one line per question with the number, sources and cost (runlog.py)
Aggregation is the template's: the median of the runs.
"""

from __future__ import annotations

import logging
import os
import statistics
from datetime import datetime

import requests

from forecasting_tools import (
    BinaryQuestion,
    GeneralLlm,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    PredictedOption,
    PredictedOptionList,
    ReasonedPrediction,
    clean_indents,
)
from forecasting_tools.data_models.data_organizer import DataOrganizer

from main import FallTemplateBot2026

from . import comment as C
from . import config, guards, research, runlog

logger = logging.getLogger(__name__)

KEY_LINES = clean_indents(
    """
    Just before your final answer, write these two lines exactly:
    KEY: one sentence naming the base rate you started from and the one or two specific facts (with dates or figures) that moved you most
    SOURCES: the outlets or sites those facts came from, comma separated
    """
)

OUTSIDE_VIEW = clean_indents(
    """
    Before anything else, take the outside view: name a reference class for this question and the base rate it gives.
    Then adjust from that anchor only as far as the specific evidence justifies.
    """
)


def _qkey(q: MetaculusQuestion) -> str:
    return str(q.id_of_question or q.page_url)


def openrouter_spend() -> float | None:
    """Total spend on the OpenRouter key so far, in USD. The cost of a question is the difference."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        r.raise_for_status()
        return float(r.json()["data"]["usage"])
    except Exception:
        return None


class BrightPandaBot(FallTemplateBot2026):
    def __init__(self, *args, budget: dict | None = None, comment_llm: GeneralLlm | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.budget = budget if budget is not None else runlog.load_budget()
        self._comment_llm = comment_llm
        self._meta: dict[str, dict] = {}

    # ---------------------------------------------------------------- models
    @classmethod
    def panda_llms(cls) -> dict:
        return {
            "default": GeneralLlm(
                model=config.FORECASTER,
                temperature=None if config.FORECASTER_EFFORT else 0.3,
                reasoning_effort=config.FORECASTER_EFFORT or None,
                timeout=600,
                allowed_tries=2,
                max_tokens=config.MAX_TOKENS_FORECASTER,
            ),
            "summarizer": GeneralLlm(model=config.PARSER, temperature=0.2, max_tokens=config.MAX_TOKENS_SMALL, allowed_tries=6),
            "researcher": "panda",
            "parser": GeneralLlm(model=config.PARSER, temperature=0, max_tokens=config.MAX_TOKENS_SMALL, allowed_tries=6),  # new OpenRouter accounts: 20 requests a minute; retries back off
        }

    # -------------------------------------------------------------- research
    async def run_research(self, question: MetaculusQuestion) -> str:
        async with self._concurrency_limiter:
            r = await research.gather(question, self.budget)
            spent = r.asknews_calls
            if any(e.startswith("asknews") for e in r.errors) and spent == 0:
                spent = config.ASKNEWS_LATEST_COST  # a failed call may still have counted; stay on the safe side
            runlog.spend_asknews(self.budget, spent)
            m = self._meta.setdefault(_qkey(question), {})
            m.update(sources=r.sources, used=r.used, research_errors=r.errors, asknews_calls=spent)
            return r.text

    # ---------------------------------------------------------------- binary
    async def _run_forecast_on_binary(self, question: BinaryQuestion, research_text: str) -> ReasonedPrediction[float]:
        prompt = clean_indents(
            f"""
            You are a superforecaster with an excellent calibration record. You are scored by a log score,
            so a confident wrong answer costs far more than a cautious right one earns.

            Question:
            {question.question_text}

            Background:
            {question.background_info}

            The question resolves by these criteria, which have not yet been met. Read every word:
            {question.resolution_criteria}

            {question.fine_print}

            Research:
            {research_text}

            Today is {datetime.now().strftime("%Y-%m-%d")}.

            Work through these in order, briefly:
            (a) Exactly what must happen for YES under the criteria above: the event, the deadline, the source that decides it,
                and any wording that could trip a careless reader.
            (b) Outside view: a reference class and its base rate, as a number.
            (c) Time left, and the outcome if nothing changes. The world changes slowly most of the time.
            (d) Inside view: the specific evidence from the research that moves you from the base rate, and how far.
            (e) The strongest case for the opposite outcome.
            (f) Calibration check: anything below 5% or above 95% needs near certain evidence. Would you take a bet at your number?
            {self._get_conditional_disclaimer_if_necessary(question)}

            {KEY_LINES}
            The last thing you write is your final answer as: "Probability: ZZ%", 0-100
            """
        )
        p = await self._binary_prompt_to_forecast(question, prompt)
        return ReasonedPrediction(prediction_value=guards.clamp_binary(p.prediction_value), reasoning=p.reasoning)

    # ------------------------------------------------------- multiple choice
    async def _multiple_choice_prompt_to_forecast(self, question: MultipleChoiceQuestion, prompt: str):
        prompt = prompt.replace("Before answering you write:", OUTSIDE_VIEW + "\nBefore answering you write:", 1)
        prompt = prompt.replace("The last thing you write", KEY_LINES + "\nThe last thing you write", 1)
        p = await super()._multiple_choice_prompt_to_forecast(question, prompt)
        probs = {o.option_name: o.probability for o in p.prediction_value.predicted_options}
        fixed = guards.floor_options(probs)
        options = [PredictedOption(option_name=k, probability=v) for k, v in fixed.items()]
        return ReasonedPrediction(prediction_value=PredictedOptionList(predicted_options=options), reasoning=p.reasoning)

    # --------------------------------------------------------- numeric, date
    async def _numeric_prompt_to_forecast(self, question, prompt: str):
        return await super()._numeric_prompt_to_forecast(question, self._with_key_lines(prompt))

    async def _date_prompt_to_forecast(self, question, prompt: str):
        return await super()._date_prompt_to_forecast(question, self._with_key_lines(prompt))

    @staticmethod
    def _with_key_lines(prompt: str) -> str:
        prompt = prompt.replace("Before answering you write:", OUTSIDE_VIEW + "\nBefore answering you write:", 1)
        return prompt.replace("The last thing you write", KEY_LINES + "\nThe last thing you write", 1)

    # ---------------------------------------------------------------- comment
    async def _research_and_make_predictions(self, question: MetaculusQuestion):
        result = await super()._research_and_make_predictions(question)
        m = self._meta.setdefault(_qkey(question), {})
        report_type = DataOrganizer.get_report_type_for_question_type(type(question))
        values = [p.prediction_value for p in result.predictions]
        readable = ", ".join(report_type.make_readable_prediction(v) for v in values)
        reasoning = self._middle_reasoning(result.predictions)
        m["fallback_body"] = C.fallback_body(reasoning)
        try:
            llm = self._comment_llm or GeneralLlm(model=config.COMMENTER, temperature=0.2, timeout=90, allowed_tries=6, max_tokens=config.MAX_TOKENS_COMMENT)
            m["comment_body"] = await llm.invoke(
                C.COMMENT_PROMPT.format(
                    question=question.question_text,
                    forecast=readable,
                    research=result.research_report[:6000],
                    reasoning=reasoning[-4000:],
                    limit=400,
                )
            )
        except Exception as e:
            m["comment_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return result

    @staticmethod
    def _middle_reasoning(predictions) -> str:
        """The reasoning of the run nearest the median, for binary; the first run otherwise."""
        if not predictions:
            return ""
        vals = [p.prediction_value for p in predictions]
        if all(isinstance(v, float) for v in vals):
            med = statistics.median(vals)
            return min(predictions, key=lambda p: abs(p.prediction_value - med)).reasoning
        return predictions[0].reasoning

    def _create_comment(self, question, research_prediction_collections, aggregated_prediction, final_cost, time_spent_in_minutes) -> str:
        from forecasting_tools import DateQuestion

        readable = C.compact(aggregated_prediction, is_date=isinstance(question, DateQuestion))
        m = self._meta.setdefault(_qkey(question), {})
        for body in (m.get("comment_body", ""), m.get("fallback_body", "")):
            text = C.build(readable, body)
            if not C.problems(text):
                m["comment"] = text
                m["forecast"] = readable
                return text
        # no comment worth sending means no forecast: a forecast without a comment cannot win
        raise ValueError(f"no comment passed the check: {C.problems(C.build(readable, m.get('comment_body', '')))}")

    # -------------------------------------------------------- one question
    async def _run_individual_question(self, question: MetaculusQuestion):
        # Questions run side by side, so the key's spend can't be split per question.
        # The exact spend is taken per run in run.py; each row carries the model price estimate.
        row = {
            "question_id": question.id_of_question,
            "post_id": question.id_of_post,
            "url": question.page_url,
            "title": question.question_text,
            "type": type(question).__name__,
            "published": bool(self.publish_reports_to_metaculus),
        }
        try:
            report = await super()._run_individual_question(question)
            row.update(ok=True, estimate_usd=round(float(report.price_estimate or 0), 4))
            return report
        except Exception as e:
            row.update(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}")
            raise
        finally:
            m = self._meta.pop(_qkey(question), {})
            row.update(
                forecast=m.get("forecast"),
                comment=m.get("comment"),
                sources=m.get("sources", []),
                research_used=m.get("used", []),
                research_errors=m.get("research_errors", []),
                asknews_calls=m.get("asknews_calls", 0),
                model=config.FORECASTER,
            )
            if row.get("ok") and self.publish_reports_to_metaculus:
                self.budget["sent"] = int(self.budget["sent"]) + 1
            runlog.write(row)
            runlog.save_budget(self.budget)  # after every question, so a cancelled run can't lose the AskNews count
