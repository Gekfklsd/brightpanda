"""One place for every setting the bot runs on.

Models are OpenRouter ids. The forecaster is chosen by compare.py on resolved
questions (see docs/model-choice.md). Change it here and nowhere else.
"""

import os

# ---- models ---------------------------------------------------------------
# Provisional until compare.py has run on resolved questions: GPT-5.4 at high
# reasoning, the model the top ten Spring 2026 bots reported using
# (Metaculus Spring 2026 FutureEval analysis).
FORECASTER = (os.getenv("PANDA_FORECASTER") or "openrouter/openai/gpt-5.4")
FORECASTER_EFFORT = (os.getenv("PANDA_FORECASTER_EFFORT") or "high")
# Pulls the number out of the forecaster's text. Needs to be reliable, not clever.
PARSER = (os.getenv("PANDA_PARSER") or "openrouter/openai/gpt-5.4-mini")
# Second research source: a search model that reads the live web.
WEB_RESEARCHER = (os.getenv("PANDA_WEB_RESEARCHER") or "openrouter/perplexity/sonar")
# Writes the short private comment from the research and the runs.
COMMENTER = (os.getenv("PANDA_COMMENTER") or "openrouter/openai/gpt-5.4-mini")

# Most each model may write per call. Without a cap the library asks for 65,536 tokens,
# which OpenRouter refuses unless the account could pay for all of it.
MAX_TOKENS_FORECASTER = 16000  # high reasoning needs room to think
MAX_TOKENS_SMALL = 2000  # parser, summarizer
MAX_TOKENS_WEB = 3000
MAX_TOKENS_COMMENT = 600

# ---- forecasting ----------------------------------------------------------
RUNS_PER_QUESTION = int(os.getenv("PANDA_RUNS") or "5")  # median of these
# Overconfidence guard. A binary forecast never goes past these.
# Log scoring punishes a confident miss far more than it rewards a confident hit.
BINARY_FLOOR = 0.03
BINARY_CEILING = 0.97
# Every multiple choice option keeps at least this much.
OPTION_FLOOR = 0.01

# ---- comments -------------------------------------------------------------
COMMENT_MAX = 500  # hard limit, characters, heading included

# ---- AskNews budget -------------------------------------------------------
# Free tier for bot makers: 1,000 calls a month, 4,000 a season.
# A "latest news" search costs 1 call, an archive search costs 5.
ASKNEWS_MONTHLY = 1000
ASKNEWS_SEASON = 4000
ASKNEWS_LATEST_COST = 1
ASKNEWS_ARCHIVE_COST = 5

# ---- tournaments ----------------------------------------------------------
FALL_2026 = 33121  # fall-futureeval-2026
TEST_AREA = "bot-testing-area"
