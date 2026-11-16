"""Run BrightPanda.

  uv run python run.py --mode tournament          the scheduled run: FutureEval Fall 2026 and MiniBench, publishes
  uv run python run.py --mode test                bot testing area, publishes (unscored)
  uv run python run.py --mode test --dry          bot testing area, nothing sent, comments printed for checking
  uv run python run.py --mode test --dry --limit 3

Rules this file keeps: one forecast per question (already forecast questions are skipped, never redone),
no human in the loop, nothing tuned on open tournament questions.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import dotenv

dotenv.load_dotenv()

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

from forecasting_tools import ApiFilter, MetaculusClient  # noqa: E402

from panda import config, runlog  # noqa: E402
from panda.bot import BrightPandaBot  # noqa: E402

logger = logging.getLogger("brightpanda")


def make_bot(publish: bool, skip_done: bool) -> BrightPandaBot:
    return BrightPandaBot(
        research_reports_per_question=1,
        predictions_per_research_report=config.RUNS_PER_QUESTION,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=publish,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=skip_done,
        extra_metadata_in_explanation=False,
        llms=BrightPandaBot.panda_llms(),
    )


async def run(mode: str, dry: bool, limit: int | None) -> int:
    from panda.bot import openrouter_spend

    missing = [k for k in ("METACULUS_TOKEN", "OPENROUTER_API_KEY") if not os.getenv(k)]
    if missing:
        print(f"BrightPanda can't run: {', '.join(missing)} not set. Add {'it' if len(missing) == 1 else 'them'} as GitHub secrets.")
        return 2
    spend_before = openrouter_spend()
    client = MetaculusClient()
    bot = make_bot(publish=not dry, skip_done=(mode == "tournament"))
    reports = []
    if mode == "tournament":
        for project in (client.CURRENT_AI_COMPETITION_ID, client.CURRENT_MINIBENCH_ID):
            reports += await bot.forecast_on_tournament(project, return_exceptions=True)
    else:
        questions = await client.get_questions_matching_filter(
            ApiFilter(allowed_tournaments=[config.TEST_AREA], allowed_statuses=["open"]),
            num_questions=limit,
            error_if_question_target_missed=False,
        ) if limit else None
        if questions is not None:
            reports = await bot.forecast_questions(questions, return_exceptions=True)
        else:
            reports = await bot.forecast_on_tournament(config.TEST_AREA, return_exceptions=True)
    spend_after = openrouter_spend()
    run_cost = None
    if spend_before is not None and spend_after is not None:
        run_cost = round(spend_after - spend_before, 4)
        bot.budget["cost_usd"] = round(float(bot.budget["cost_usd"]) + run_cost, 4)
    runlog.save_budget(bot.budget)
    if reports:
        runlog.write({"run": mode, "dry": dry, "questions": len(reports), "cost_usd": run_cost})

    ok = [r for r in reports if not isinstance(r, BaseException)]
    bad = [r for r in reports if isinstance(r, BaseException)]
    print(f"\nBrightPanda: {len(ok)} forecast{'s' if len(ok) != 1 else ''}, {len(bad)} failed, {'DRY RUN, nothing sent' if dry else 'sent'}")
    if dry:
        for r in ok:
            print(f"\n--- {r.question.page_url}\n{r.explanation}\n({len(r.explanation)} characters)")
    for e in bad:
        print(f"failed: {type(e).__name__}: {str(e)[:300]}")
    # a whole run of failures is a broken bot, so the job goes red and GitHub says so
    return 1 if reports and not ok else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["tournament", "test"], default="tournament")
    ap.add_argument("--dry", action="store_true", help="send nothing to Metaculus")
    ap.add_argument("--limit", type=int, default=None, help="test mode only: at most this many questions")
    a = ap.parse_args()
    if a.mode == "tournament" and a.limit:
        sys.exit("--limit is for test mode only")
    sys.exit(asyncio.run(run(a.mode, a.dry, a.limit)))


if __name__ == "__main__":
    main()
