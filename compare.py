"""Compare forecasting models, and prompts, on questions that have already resolved.

Only resolved questions are used, never open ones (the tournament's no human in the loop rule).
Only questions that opened after CUTOFF are used, so a model cannot simply remember the answer.
Each model sees the question as it stood when it opened ("Today is <open date>") and no research,
so the test measures the model's judgement, not the search.

  uv run python compare.py --list                                  how many resolved questions there are
  uv run python compare.py --models openrouter/openai/gpt-5.4 openrouter/anthropic/claude-sonnet-5.5 --n 60 --runs 3 --max-usd 15
  uv run python compare.py --prompt-test --models openrouter/openai/gpt-5.4 --n 60    ours against the template's prompt

Writes docs/model-choice.md (or docs/prompt-test.md) and the raw rows to state/compare-*.json.
Scores: Metaculus baseline score (100 x (log2 p_actual + 1), higher is better, 0 is a coin flip)
and Brier (lower is better), with a bootstrap 90% range on the difference from the first model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

import dotenv

dotenv.load_dotenv()

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

from forecasting_tools import ApiFilter, BinaryQuestion, GeneralLlm, MetaculusClient  # noqa: E402

import main  # noqa: E402
from panda import bot as B  # noqa: E402
from panda import config, guards  # noqa: E402

ROOT = Path(__file__).resolve().parent
CUTOFF = datetime(2026, 9, 28, tzinfo=timezone.utc)  # Fall 2026 season start, after every candidate's training data
PROJECTS = [config.FALL_2026, "minibench"]
SOURCE = "manifold"


NOISE = ("coinflip", "coin flip", "daily ", "will i ", " my ", "i will", "this market", "pangram", "mistress")


def manifold_questions(n: int | None) -> list[BinaryQuestion]:
    """Resolved yes/no questions from Manifold's public API, created after CUTOFF.

    Metaculus hides question resolutions from bot accounts (checked 16 Nov 2026 with scripts/probe.py:
    the resolution field is withheld on every resolved question, tournament or not), so the
    comparison uses Manifold, a public forecasting site with an open API."""
    import urllib.request

    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "brightpanda-bench"})
        return json.load(urllib.request.urlopen(req, timeout=30))

    cut_ms = CUTOFF.timestamp() * 1000
    picked = []
    for off in range(0, 3000, 100):
        try:
            page = get(f"https://api.manifold.markets/v0/search-markets?term=&filter=resolved&contractType=BINARY&sort=newest&limit=100&offset={off}")
        except Exception:
            break  # the search stops paging past a fixed depth
        if not page:
            break
        for m in page:
            t = m.get("question", "")
            if (m.get("createdTime", 0) > cut_ms and m.get("resolution") in ("YES", "NO")
                    and m.get("uniqueBettorCount", 0) >= 25 and not any(w in f" {t.lower()} " for w in NOISE)):
                picked.append(m)
        if page[-1].get("createdTime", 0) < cut_ms:
            break
    random.Random(7).shuffle(picked)
    out = []
    for m in picked[: (n or len(picked))]:
        try:
            full = get(f"https://api.manifold.markets/v0/market/{m['id']}")
        except Exception:
            full = m
        out.append(BinaryQuestion(
            question_text=m["question"], id_of_question=abs(hash(m["id"])) % 10**9, id_of_post=0, page_url=m.get("url", ""),
            resolution_criteria=(full.get("textDescription") or "Resolves per the question title.")[:3000], fine_print="",
            background_info="", open_time=datetime.fromtimestamp(m["createdTime"] / 1000, timezone.utc),
            resolution_string=m["resolution"].lower(),
        ))
    return out


async def resolved_questions(n: int | None) -> list[BinaryQuestion]:
    if SOURCE == "manifold":
        return manifold_questions(n)
    client = MetaculusClient()
    out = []
    for project in PROJECTS:
        qs = await client.get_questions_matching_filter(
            ApiFilter(allowed_tournaments=[project], allowed_statuses=["resolved"], allowed_types=["binary"],
                      open_time_gt=CUTOFF),
            num_questions=None, error_if_question_target_missed=False,
        )
        out += [q for q in qs if (q.resolution_string or "").lower() in ("yes", "no")]
    seen, uniq = set(), []
    for q in out:
        if q.id_of_question not in seen:
            seen.add(q.id_of_question)
            uniq.append(q)
    random.Random(7).shuffle(uniq)  # fixed sample, same for every model
    return uniq[:n] if n else uniq


def baseline_score(p: float, yes: bool) -> float:
    return 100 * (math.log2(p if yes else 1 - p) + 1)


def brier(p: float, yes: bool) -> float:
    return (p - (1.0 if yes else 0.0)) ** 2


class FixedDay:
    """Stands in for datetime inside the bot module so 'Today is' reads the question's open date."""

    day: datetime = datetime.now()

    @classmethod
    def now(cls, tz=None):
        return cls.day


def make_bot(model: str) -> B.BrightPandaBot:
    llms = B.BrightPandaBot.panda_llms()
    effort = config.FORECASTER_EFFORT if "perplexity" not in model else None
    llms["default"] = GeneralLlm(model=model, temperature=None if effort else 0.3, reasoning_effort=effort, timeout=600, allowed_tries=2, max_tokens=config.MAX_TOKENS_FORECASTER)
    return B.BrightPandaBot(
        research_reports_per_question=1, predictions_per_research_report=1, use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=False, folder_to_save_reports_to=None, skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=False, llms=llms, budget={},
    )


NO_RESEARCH = "No research is available for this test. Use what you know up to today's date and base rates."


async def forecast(bot, q: BinaryQuestion, runs: int, prompt: str) -> float:
    FixedDay.day = q.open_time.replace(tzinfo=None) if q.open_time else datetime.now()
    B.datetime = FixedDay
    main.datetime = FixedDay
    vals = []
    for _ in range(runs):
        if prompt == "ours":
            p = await bot._run_forecast_on_binary(q, NO_RESEARCH)
            vals.append(p.prediction_value)
        else:
            p = await main.FallTemplateBot2026._run_forecast_on_binary(bot, q, NO_RESEARCH)
            vals.append(p.prediction_value)
    return statistics.median(vals)


def boot_diff(a: list[float], b: list[float], higher_better=True, k=4000) -> tuple[float, float, float]:
    rnd = random.Random(1)
    d = [x - y for x, y in zip(a, b)]
    means = sorted(statistics.fmean(rnd.choices(d, k=len(d))) for _ in range(k))
    return statistics.fmean(d), means[int(0.05 * k)], means[int(0.95 * k)]


async def run(models: list[str], n: int | None, runs: int, max_usd: float, prompt_test: bool) -> None:
    qs = await resolved_questions(n)
    print(f"{len(qs)} resolved binary questions opened after {CUTOFF.date()}")
    arms = [(m, "ours") for m in models]
    if prompt_test:
        arms = [(models[0], "ours"), (models[0], "template")]
    start = B.openrouter_spend()
    rows = {f"{m}|{p}": [] for m, p in arms}
    for q in qs:
        yes = q.resolution_string.lower() == "yes"
        for m, p in arms:
            spent = (B.openrouter_spend() or 0) - (start or 0)
            if spent > max_usd:
                print(f"stopped at the ${max_usd} cap")
                break
            try:
                v = await forecast(make_bot(m), q, runs, p)
            except Exception as e:
                print(f"  {m} {p} failed on {q.id_of_question}: {type(e).__name__}")
                continue
            v = guards.clamp_binary(v)
            rows[f"{m}|{p}"].append(dict(q=q.id_of_question, title=q.question_text, yes=yes, p=v))
        else:
            continue
        break
    end = B.openrouter_spend()
    write_report(rows, runs, prompt_test, None if start is None or end is None else end - start)


def write_report(rows: dict, runs: int, prompt_test: bool, cost: float | None) -> None:
    name = "prompt-test" if prompt_test else "model-choice"
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / f"compare-{name}.json").write_text(json.dumps(rows, indent=1))
    keys = list(rows)
    common = set.intersection(*[{r["q"] for r in rows[k]} for k in keys]) if keys else set()
    by = {k: {r["q"]: r for r in rows[k]} for k in keys}
    ids = sorted(common)
    lines = [f"# {'Prompt test' if prompt_test else 'Model choice'}", "",
             f"Run {datetime.now(timezone.utc):%d %b %Y}. {len(ids)} resolved binary questions every arm answered, "
             f"opened after {CUTOFF:%d %b %Y} (source: {SOURCE}), no research, median of {runs} run(s).",
             f"Cost of this test: {'$%.2f (OpenRouter key usage)' % cost if cost is not None else 'not measured'}.", "",
             "| Arm | Baseline score (higher better) | Brier (lower better) | Difference from first arm, 90% range |",
             "|---|---|---|---|"]
    ref = [baseline_score(by[keys[0]][i]["p"], by[keys[0]][i]["yes"]) for i in ids] if keys else []
    for k in keys:
        bs = [baseline_score(by[k][i]["p"], by[k][i]["yes"]) for i in ids]
        br = [brier(by[k][i]["p"], by[k][i]["yes"]) for i in ids]
        if not ids:
            continue
        if k == keys[0]:
            diff = "reference"
        else:
            m, lo, hi = boot_diff(bs, ref)
            diff = f"{m:+.1f} ({lo:+.1f} to {hi:+.1f})"
        lines.append(f"| {k.replace('|', ' / ')} | {statistics.fmean(bs):.1f} | {statistics.fmean(br):.3f} | {diff} |")
    lines += ["", "A range that crosses zero means the test cannot tell the two apart on this many questions."]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / f"{name}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main_cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=[config.FORECASTER])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-usd", type=float, default=10.0)
    ap.add_argument("--prompt-test", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--source", choices=["manifold", "metaculus"], default="manifold")
    a = ap.parse_args()
    global SOURCE
    SOURCE = a.source
    if a.list:
        qs = asyncio.run(resolved_questions(None))
        print(f"{len(qs)} resolved binary questions opened after {CUTOFF.date()}; {sum(q.resolution_string.lower() == 'yes' for q in qs)} resolved yes")
        return
    asyncio.run(run(a.models, a.n, a.runs, a.max_usd, a.prompt_test))


if __name__ == "__main__":
    main_cli()
