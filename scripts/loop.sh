#!/usr/bin/env bash
# One GitHub job that forecasts every 15 minutes for about 5 hours 40, then starts the next job.
# GitHub's own timer proved unreliable (2 runs in 15 hours on 16-17 Nov 2026), and questions are
# open for about 3 hours, so the bot keeps its own clock. The cron in forecast.yaml stays as a backstop
# that restarts the chain if it ever breaks; the concurrency group keeps it to one job at a time.
set -u
STOP_AFTER=${STOP_AFTER:-20400}   # seconds, 5h40, inside the 6 hour job limit
EVERY=${EVERY:-900}               # seconds between rounds
start=$(date +%s)
keep() {
  git add logs/runs.age.jsonl state/budget.json 2>/dev/null || true
  git diff --cached --quiet && return 0
  git commit -qm "log: forecast run $(date -u +%Y-%m-%dT%H:%MZ)"
  for i in 1 2 3; do git pull --rebase -q && git push -q && return 0; sleep 5; done
  echo "::warning::could not push the log"
}
while :; do
  round=$(date +%s)
  uv run python run.py --mode tournament || echo "::warning::round failed, carrying on"
  keep
  now=$(date +%s)
  [ $((now - start + EVERY)) -ge "$STOP_AFTER" ] && break
  sleep $(( EVERY - (now - round) > 0 ? EVERY - (now - round) : 0 ))
done
