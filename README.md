# BrightPanda

A forecasting bot for the Metaculus FutureEval bot tournament.

It is built on Metaculus's official template ([metac-bot-template](https://github.com/Metaculus/metac-bot-template)). `main.py` and `bot_helpers.py` are theirs, as they came, and their README is kept in `docs/template-README.md`. Everything of ours is in `panda/`.

## How it forecasts

1. Research. AskNews and a live web search run side by side. If one fails, the other carries the question.
2. Outside view first. The prompt asks for a reference class and its base rate before any of the news.
3. Five runs, then the median.
4. Guards. A yes or no forecast stays between 3% and 97%, and every option in a multiple choice question keeps at least 1%. Under a log score a confident miss costs far more than a confident hit earns.
5. A short private comment on every forecast with the base rate, the one or two facts that moved the number, and where they came from. It is checked for length and substance before anything is sent. No comment, no forecast.

## Running

```bash
uv sync
uv run pytest -q
uv run python run.py --mode test --dry --limit 3
```

On GitHub the Forecast workflow runs every 20 minutes. The testing area run and the model comparison are started by hand.

Keys go in as repository secrets: `METACULUS_TOKEN`, `OPENROUTER_API_KEY`, and optionally `ASKNEWS_CLIENT_ID` with `ASKNEWS_SECRET`.

## Rules it keeps

- No person in the loop. The bot is tuned only on the unscored testing area and on questions that have already resolved.
- One forecast per question. A question already forecast is skipped, never redone.
- Comments are private and under 500 characters.
- The run log is encrypted before it is committed, so forecasts on open questions stay private.

## Licence

Our code in `panda/`, `run.py`, `compare.py`, `scripts/` and `tests/` is MIT. The template files keep Metaculus's terms.
