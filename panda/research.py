"""Research: AskNews and a live web search model, side by side.

The top Spring 2026 bots ran research tools in parallel. If one source fails or
is not set up, the other carries the question. AskNews is free but capped
(1,000 calls a month), so it is paced: the full search (latest news plus the
archive, 6 calls) while under the month's pace, the latest news only (1 call)
when ahead of it, none when the cap is reached.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config

logger = logging.getLogger(__name__)

FULL = "full"
LATEST = "latest"
NONE = "none"


def asknews_plan(used_month: int, used_season: int, today: datetime | None = None) -> str:
    """How much AskNews this question may use. Pure, tested."""
    today = today or datetime.now(timezone.utc)
    days = calendar.monthrange(today.year, today.month)[1]
    pace = config.ASKNEWS_MONTHLY * today.day / days  # calls allowed by today
    full = config.ASKNEWS_LATEST_COST + config.ASKNEWS_ARCHIVE_COST
    left_month = config.ASKNEWS_MONTHLY - used_month
    left_season = config.ASKNEWS_SEASON - used_season
    left = min(left_month, left_season)
    if used_month + full <= pace and full <= left:
        return FULL
    if config.ASKNEWS_LATEST_COST <= left:
        return LATEST
    return NONE


def asknews_ready() -> bool:
    return bool(os.getenv("ASKNEWS_API_KEY") or (os.getenv("ASKNEWS_CLIENT_ID") and os.getenv("ASKNEWS_SECRET")))


def web_ready() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


@dataclass
class Research:
    text: str = ""
    sources: list[str] = field(default_factory=list)
    asknews_calls: int = 0
    used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _fmt_articles(articles) -> tuple[str, list[str]]:
    out, names = "", []
    for a in sorted(articles, key=lambda x: x.pub_date, reverse=True):
        when = a.pub_date.strftime("%d %b %Y")
        out += f"- {a.eng_title} ({a.source_id}, {when}): {a.summary}\n"
        if a.source_id and a.source_id not in names:
            names.append(a.source_id)
    return out, names


async def asknews(query: str, plan: str) -> tuple[str, list[str], int]:
    from asknews_sdk import AsyncAskNewsSDK

    calls = 0
    async with AsyncAskNewsSDK(
        client_id=os.getenv("ASKNEWS_CLIENT_ID") or None,
        client_secret=os.getenv("ASKNEWS_SECRET") or None,
        api_key=None if os.getenv("ASKNEWS_CLIENT_ID") else os.getenv("ASKNEWS_API_KEY"),
        scopes={"news"},
    ) as ask:
        hot = await ask.news.search_news(query=query, n_articles=8, return_type="both", strategy="latest news")
        calls += config.ASKNEWS_LATEST_COST
        articles = list(hot.as_dicts or [])
        if plan == FULL:
            await asyncio.sleep(10)  # free tier: one call per 10 seconds
            hist = await ask.news.search_news(query=query, n_articles=10, return_type="both", strategy="news knowledge")
            calls += config.ASKNEWS_ARCHIVE_COST
            articles += list(hist.as_dicts or [])
    text, names = _fmt_articles(articles)
    return (text or "No articles found.\n"), names, calls


WEB_PROMPT = """You are the research assistant to a professional forecaster. Search the web now.

Question: {question}

How it resolves (read this closely, every word counts):
{criteria}

{fine_print}

Give a tight rundown, newest first, with a date on every fact:
1. The current status of exactly what the resolution criteria measure, and the latest figure if there is one.
2. Base rates: how often things like this have happened before, with the reference class.
3. Scheduled events before the resolution date that could decide it.
4. What experts, officials or prediction markets currently expect.
Name the outlet for each fact. Do not forecast. Under 400 words."""


async def web(question, model: str = config.WEB_RESEARCHER) -> tuple[str, list[str]]:
    from forecasting_tools import GeneralLlm

    llm = GeneralLlm(model=model, temperature=0, timeout=120, allowed_tries=2, max_tokens=config.MAX_TOKENS_WEB)
    text = await llm.invoke(
        WEB_PROMPT.format(
            question=question.question_text,
            criteria=question.resolution_criteria or "",
            fine_print=question.fine_print or "",
        )
    )
    return text, ["web search"]


async def gather(question, budget: dict) -> Research:
    from .runlog import asknews_used_this_month

    r = Research()
    tasks, kinds = [], []
    plan = asknews_plan(asknews_used_this_month(budget), int(budget["asknews_season"])) if asknews_ready() else NONE
    if plan != NONE:
        tasks.append(asknews(question.question_text, plan))
        kinds.append("asknews")
    if web_ready():
        tasks.append(web(question))
        kinds.append("web")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    parts = []
    for kind, res in zip(kinds, results):
        if isinstance(res, BaseException):
            r.errors.append(f"{kind}: {type(res).__name__}: {str(res)[:200]}")
            logger.warning("research source %s failed: %s", kind, res)
            continue
        if kind == "asknews":
            text, names, calls = res
            r.asknews_calls += calls
            parts.append(f"## News (AskNews, {plan} search)\n{text}")
            r.sources += names
        else:
            text, names = res
            parts.append(f"## Web search\n{text}")
            r.sources += names
        r.used.append(kind)
    r.text = "\n\n".join(parts) if parts else "No research could be gathered. Rely on base rates and the question text."
    return r
