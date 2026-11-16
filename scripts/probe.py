"""Count resolved questions under a few filters, to find why compare.py saw none. Reads the API only."""
import asyncio
from datetime import datetime, timezone

import dotenv

dotenv.load_dotenv()
from forecasting_tools import ApiFilter, MetaculusClient  # noqa: E402

CUT = datetime(2026, 9, 28, tzinfo=timezone.utc)


async def count(label, **kw):
    try:
        qs = await MetaculusClient().get_questions_matching_filter(ApiFilter(**kw), num_questions=None, error_if_question_target_missed=False)
        res = {}
        for q in qs:
            res[str(q.resolution_string)] = res.get(str(q.resolution_string), 0) + 1
        print(f"{label}: {len(qs)} questions, resolutions {res}")
        if qs:
            q = qs[0]
            print(f"   e.g. {type(q).__name__} open {q.open_time} status? {getattr(q, 'state', None)} res {q.resolution_string!r}")
            j = q.api_json or {}
            qj = j.get("question") or {}
            def walk(d, path=""):
                for k, v in (d.items() if isinstance(d, dict) else []):
                    if "resol" in k.lower() or k in ("status", "actual_close_time", "include_bots_in_aggregates"):
                        print(f"   {path}{k} = {str(v)[:120]!r}")
                    if isinstance(v, dict) and len(path) < 30:
                        walk(v, path + k + ".")
            walk(j)
    except Exception as e:
        print(f"{label}: error {type(e).__name__}: {str(e)[:200]}")


async def main():
    for t in (33121,):
        await count(f"{t} resolved", allowed_tournaments=[t], allowed_statuses=["resolved"])
        await count(f"{t} closed", allowed_tournaments=[t], allowed_statuses=["closed"])
        await count(f"{t} resolved binary after cut", allowed_tournaments=[t], allowed_statuses=["resolved"], allowed_types=["binary"], open_time_gt=CUT)

asyncio.run(main())
