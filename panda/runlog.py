"""The run log: every question, the number sent, the sources, the cost.

The repo is public, and a forecast on an open question must not be readable by
others, so each line is encrypted with an age public key before it is committed
(logs/runs.age.jsonl). Only the private key on the owner's Mac can read it
(scripts/readlog.py). Counts that give nothing away (calls, cost, how many sent)
go to state/budget.json in the clear, so the bot can keep to its AskNews budget.

Without PANDA_LOG_PUBKEY set (tests, a local dry run) lines go in the clear to
logs/local.jsonl, which is git ignored.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
STATE = ROOT / "state"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encrypt(text: str, pubkey: str) -> str:
    import pyrage

    recipient = pyrage.x25519.Recipient.from_str(pubkey)
    return base64.b64encode(pyrage.encrypt(text.encode(), [recipient])).decode()


def write(row: dict, logs: Path | None = None) -> Path:
    logs = logs or LOGS
    row = {"at": now(), **row}
    logs.mkdir(parents=True, exist_ok=True)
    pub = os.getenv("PANDA_LOG_PUBKEY", "").strip()
    line = json.dumps(row, ensure_ascii=False)
    if pub:
        path = logs / "runs.age.jsonl"
        out = json.dumps({"at": row["at"], "age": _encrypt(line, pub)})
    else:
        path = logs / "local.jsonl"
        out = line
    with path.open("a", encoding="utf-8") as f:
        f.write(out + "\n")
    return path


# ---- the budget counter (clear text, nothing secret in it) ---------------

def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def load_budget(state: Path | None = None) -> dict:
    state = state or STATE
    try:
        b = json.loads((state / "budget.json").read_text())
    except Exception:
        b = {}
    b.setdefault("asknews_season", 0)
    b.setdefault("asknews_by_month", {})
    b.setdefault("sent", 0)
    b.setdefault("cost_usd", 0.0)
    return b


def save_budget(b: dict, state: Path | None = None) -> None:
    state = state or STATE
    state.mkdir(parents=True, exist_ok=True)
    (state / "budget.json").write_text(json.dumps(b, indent=2, sort_keys=True) + "\n")


def asknews_used_this_month(b: dict) -> int:
    return int(b["asknews_by_month"].get(_month(), 0))


def spend_asknews(b: dict, calls: int) -> None:
    m = _month()
    b["asknews_by_month"][m] = int(b["asknews_by_month"].get(m, 0)) + calls
    b["asknews_season"] = int(b["asknews_season"]) + calls
