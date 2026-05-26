from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from .common import read_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize remote Stage 2 judge JSONL results.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)

    rows = read_jsonl(args.results)
    statuses: Counter[str] = Counter()
    error_codes: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    accepted_ids: list[str] = []

    for row in rows:
        status = row.get("status") or nested(row, "remote_result", "status") or ""
        error_code = row.get("error_code") or nested(row, "remote_result", "error_code") or ""
        answer = row.get("answer") or row.get("judge_call") or {}
        verdict = answer.get("verdict") if isinstance(answer, dict) else ""
        statuses[str(status)] += 1
        error_codes[str(error_code)] += 1
        verdicts[str(verdict)] += 1
        if status == "accepted":
            accepted_ids.append(str(row.get("id") or row.get("problem_id") or ""))

    summary = {
        "total_count": len(rows),
        "accepted_count": statuses.get("accepted", 0),
        "accepted_ids": accepted_ids,
        "status_counts": dict(sorted(statuses.items())),
        "error_code_counts": dict(sorted(error_codes.items())),
        "verdict_counts": dict(sorted(verdicts.items())),
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def nested(row: dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
