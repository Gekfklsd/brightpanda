"""Read the bot's run log on the owner's Mac.

The log in the repo is encrypted (the repo is public, and forecasts on open questions must not be
readable by others). The private key is in the Mac's Keychain as brightpanda.runlog / age-identity.

  git pull && uv run python scripts/readlog.py            the last 20 questions
  uv run python scripts/readlog.py --all --json           everything, one JSON row per line

Reading the log is fine. Changing the bot because of how open questions are going is not
(the tournament's no human in the loop rule). Tune only on resolved questions with compare.py.
"""

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import pyrage

LOG = Path(__file__).resolve().parent.parent / "logs" / "runs.age.jsonl"


def identity():
    out = subprocess.run(["security", "find-generic-password", "-s", "brightpanda.runlog", "-a", "age-identity", "-w"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit("The log key is not in this Mac's Keychain (brightpanda.runlog).")
    return pyrage.x25519.Identity.from_str(out.stdout.strip())


def rows():
    ident = identity()
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text().splitlines():
        if line.strip():
            out.append(json.loads(pyrage.decrypt(base64.b64decode(json.loads(line)["age"]), [ident])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rs = rows() if a.all else rows()[-20:]
    for r in rs:
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
            continue
        if "run" in r:
            c = f"${r['cost_usd']:.3f}" if r.get("cost_usd") is not None else "cost ?"
            print(f"{r['at'][:16]}  run of {r['questions']} question(s), {c}{' (dry)' if r.get('dry') else ''}")
            continue
        cost = f"est ${r['estimate_usd']:.3f}" if r.get("estimate_usd") is not None else ""

        state = r.get("forecast") if r.get("ok") else f"FAILED {r.get('error', '')[:80]}"
        print(f"{r['at'][:16]}  {state:>14}  {cost:>12}  {', '.join(r.get('sources', [])[:3]):30.30}  {r['title'][:70]}")


if __name__ == "__main__":
    main()
