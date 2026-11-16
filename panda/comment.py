"""The private comment every forecast needs.

The rules: a comment under each forecast or the bot cannot win, private, short,
the key sources and the one or two facts that moved the number. Long, low value
or raw AI text counts as spam. So the comment is built here and checked here,
and a forecast whose comment fails the check is not sent (bot.py).
"""

from __future__ import annotations

import re

from . import config

BANNED = [
    "as an ai",
    "language model",
    "i cannot",
    "i can't",
    "certainly!",
    "great question",
    "in conclusion",
    "it is important to note",
    "delve",
]

COMMENT_PROMPT = """You write the short private note a forecasting bot leaves under its forecast.

Question: {question}
Final forecast: {forecast}

Research the bot read:
{research}

How the bot reasoned (one of its runs):
{reasoning}

Write at most {limit} characters, plain text, no heading, no bullet points, no markdown.
Say only: the base rate or reference class used, the one or two specific facts that moved
the number most (with a date or figure where there is one), and name the sources those facts
came from by outlet or site name (no URLs). Do not restate the question. Do not hedge.
No words like "As an AI". If the research found nothing useful, say what the forecast rests on instead."""


def heading(readable_forecast: str) -> str:
    # forecasting-tools requires the explanation to start with '#'
    return f"# BrightPanda forecast: {readable_forecast}"


def tidy(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fit(body: str, room: int) -> str:
    """Cut to `room` characters on a sentence end if one is near, else a word end."""
    body = tidy(body)
    if len(body) <= room:
        return body
    cut = body[:room]
    end = max(cut.rfind(". "), cut.rfind("; "))
    if end >= room * 0.6:
        return cut[: end + 1].strip()
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(",;: ") + "."


def build(readable_forecast: str, body: str, limit: int = config.COMMENT_MAX) -> str:
    head = heading(readable_forecast)
    room = limit - len(head) - 1
    return f"{head}\n{fit(body, room)}"


def problems(comment: str, limit: int = config.COMMENT_MAX) -> list[str]:
    """Why a comment must not be sent. Empty list means it is fine."""
    out = []
    if len(comment) > limit:
        out.append(f"too long ({len(comment)} > {limit})")
    lines = comment.split("\n", 1)
    if not lines[0].startswith("# BrightPanda forecast: "):
        out.append("no forecast heading")
    body = lines[1] if len(lines) > 1 else ""
    if len(body) < 60:
        out.append("body too thin to be worth reading")
    low = body.lower()
    for b in BANNED:
        if b in low:
            out.append(f"reads as raw AI text ({b!r})")
    return out


def fallback_body(reasoning: str) -> str:
    """When the comment model fails: the KEY and SOURCES lines the forecaster wrote."""
    key = re.search(r"^\s*KEY:\s*(.+)$", reasoning or "", re.M | re.I)
    src = re.search(r"^\s*SOURCES:\s*(.+)$", reasoning or "", re.M | re.I)
    parts = []
    if key:
        parts.append(key.group(1).strip())
    if src:
        parts.append("Sources: " + src.group(1).strip())
    return " ".join(parts)
