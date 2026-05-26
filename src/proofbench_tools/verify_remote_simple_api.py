from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
from typing import Any, Sequence
import urllib.error
import urllib.request
import uuid

from .common import (
    DEFAULT_REMOTE_SIMPLE_API_BASE_URLS,
    build_judge_rows,
    code_sha256,
    extract_answer,
    read_jsonl,
    write_jsonl,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Stage 2 proofbench candidate certificates with the remote simple-api judge."
    )
    parser.add_argument("--input", type=Path, help="Prepared JSONL rows with problem and answer.")
    parser.add_argument("--problems", type=Path, help="Problem JSONL, used with --candidates.")
    parser.add_argument("--candidates", type=Path, help="Candidate answer JSONL, used with --problems.")
    parser.add_argument("--judge-input", type=Path, help="Optional path to write prepared judge input.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--base-urls",
        default=os.environ.get(
            "PROOFBENCH_REMOTE_SIMPLE_API_BASE_URLS",
            ",".join(DEFAULT_REMOTE_SIMPLE_API_BASE_URLS),
        ),
        help=(
            "Comma-separated remote simple-api backend pool. "
            "Can also be set with PROOFBENCH_REMOTE_SIMPLE_API_BASE_URLS."
        ),
    )
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--request-timeout-seconds", type=int, default=20)
    parser.add_argument("--run-timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--run-id-prefix", default="proofbench-residual100")
    parser.add_argument("--no-cache", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.input:
        rows = read_jsonl(args.input)
    else:
        if not args.problems or not args.candidates:
            raise SystemExit("provide --input or both --problems and --candidates")
        rows = build_judge_rows(read_jsonl(args.problems), read_jsonl(args.candidates))
    if args.judge_input:
        write_jsonl(args.judge_input, rows)

    base_urls = normalize_base_urls(args.base_urls)
    base_url = select_base_url(
        base_urls,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    started = time.monotonic()
    results = verify_rows(
        rows,
        base_url=base_url,
        max_workers=args.max_workers,
        request_timeout_seconds=args.request_timeout_seconds,
        run_timeout_seconds=args.run_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        run_id_prefix=args.run_id_prefix,
        cache=not args.no_cache,
    )
    write_jsonl(args.output, results)
    status_counts = Counter(str(row.get("status") or "") for row in results)
    error_code_counts = Counter(str(row.get("error_code") or "") for row in results)
    verdict_counts = Counter(
        str((row.get("answer") or {}).get("verdict") or "")
        for row in results
        if isinstance(row.get("answer"), dict)
    )
    summary = {
        "schema_version": 1,
        "total_count": len(results),
        "accepted_count": status_counts.get("accepted", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "error_code_counts": dict(sorted(error_code_counts.items())),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "output": str(args.output),
        "judge_input": str(args.judge_input) if args.judge_input else None,
        "remote": {
            "base_url": base_url,
            "candidate_base_urls": list(base_urls),
            "max_workers": max(1, args.max_workers),
            "cache": not args.no_cache,
            "request_timeout_seconds": args.request_timeout_seconds,
            "run_timeout_seconds": args.run_timeout_seconds,
            "poll_interval_seconds": args.poll_interval_seconds,
            "run_id_prefix": args.run_id_prefix,
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["accepted_count"] == summary["total_count"] else 1


def verify_rows(
    rows: Sequence[dict[str, Any]],
    *,
    base_url: str,
    max_workers: int,
    request_timeout_seconds: int,
    run_timeout_seconds: int,
    poll_interval_seconds: float,
    run_id_prefix: str,
    cache: bool,
) -> list[dict[str, Any]]:
    worker_count = max(1, int(max_workers))

    def verify_one(index_and_row: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, row = index_and_row
        problem = row.get("problem")
        answer = row.get("answer") or row.get("judge_call")
        if not isinstance(problem, dict) or not isinstance(answer, dict):
            raw_result = raw_result_payload(
                run_id=None,
                status="malformed",
                error_code="REMOTE_INPUT_MALFORMED",
                message="row must include problem and answer objects",
            )
        else:
            raw_result = run_remote_simple_api_one(
                problem,
                extract_answer({"answer": answer}),
                base_url=base_url,
                max_workers=worker_count,
                request_timeout_seconds=request_timeout_seconds,
                run_timeout_seconds=run_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                run_id_prefix=run_id_prefix,
                cache=cache,
                index=index,
            )
        return {
            **row,
            "status": str(raw_result.get("status") or ""),
            "error_code": str(raw_result.get("error_code") or ""),
            "code_sha256": (
                code_sha256(answer["code"])
                if isinstance(answer, dict) and isinstance(answer.get("code"), str)
                else ""
            ),
            "remote_result": raw_result,
        }

    indexed = list(enumerate(rows))
    if worker_count == 1:
        return [verify_one(item) for item in indexed]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(verify_one, indexed))


def run_remote_simple_api_one(
    problem: dict[str, Any],
    answer: dict[str, Any],
    *,
    base_url: str,
    max_workers: int,
    request_timeout_seconds: int,
    run_timeout_seconds: int,
    poll_interval_seconds: float,
    run_id_prefix: str,
    cache: bool,
    index: int,
) -> dict[str, Any]:
    if answer.get("call") != "judge":
        return raw_result_payload(
            run_id=None,
            status="malformed",
            error_code="REMOTE_SIMPLE_API_INVALID_ANSWER",
            message="answer.call must be judge",
        )
    verdict = str(answer.get("verdict") or "")
    code = answer.get("code")
    if verdict not in {"true", "false"} or not isinstance(code, str) or not code.strip():
        return raw_result_payload(
            run_id=None,
            status="malformed",
            error_code="REMOTE_SIMPLE_API_INVALID_ANSWER",
            message="answer must include verdict true/false and non-empty code",
        )

    run_id = remote_run_id(run_id_prefix, problem, index=index)
    payload = {
        "run_id": run_id,
        "solver_text": single_certificate_solver_text(verdict=verdict, code=code),
        "problems": [problem],
        "max_workers": max(1, int(max_workers)),
        "problems_per_shard": 1,
        "cache": bool(cache),
    }
    try:
        simple_api_json_request(
            "POST",
            f"{base_url.rstrip('/')}/runs",
            payload=payload,
            timeout=request_timeout_seconds,
        )
        detail = poll_remote_simple_api_run(
            base_url=base_url,
            run_id=run_id,
            request_timeout_seconds=request_timeout_seconds,
            run_timeout_seconds=run_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        return raw_result_payload(
            run_id=run_id,
            status="error",
            error_code="REMOTE_SIMPLE_API_REQUEST_FAILED",
            message=f"{type(exc).__name__}: {exc}",
        )
    return raw_result_from_simple_api_detail(
        detail,
        run_id=run_id,
        base_url=base_url,
        verdict=verdict,
    )


def poll_remote_simple_api_run(
    *,
    base_url: str,
    run_id: str,
    request_timeout_seconds: int,
    run_timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + float(run_timeout_seconds)
    while True:
        detail = simple_api_json_request(
            "GET",
            f"{base_url.rstrip('/')}/runs/{run_id}",
            timeout=request_timeout_seconds,
        )
        status = str(detail.get("status") or "")
        if status not in {"running", "stopping"}:
            return detail
        if time.monotonic() >= deadline:
            return {**detail, "status": "timeout"}
        time.sleep(max(0.1, float(poll_interval_seconds)))


def raw_result_from_simple_api_detail(
    detail: dict[str, Any],
    *,
    run_id: str,
    base_url: str,
    verdict: str,
) -> dict[str, Any]:
    summary = detail.get("summary")
    progress = detail.get("progress")
    remote_url = f"{base_url.rstrip('/')}/runs/{run_id}"
    if isinstance(summary, dict):
        accepted = int(summary.get("accepted") or 0)
        rejected = int(summary.get("rejected") or 0)
        errors = int(summary.get("errors") or 0)
        total = int(summary.get("totalProblems") or 0)
        if total == 1 and accepted == 1:
            return raw_result_payload(
                run_id=run_id,
                status="accepted",
                error_code="",
                message="remote simple-api accepted certificate",
                verdict=verdict,
                remote_url=remote_url,
                summary=summary,
                progress=progress,
            )
        if rejected > 0:
            return raw_result_payload(
                run_id=run_id,
                status="incorrect",
                error_code="REMOTE_SIMPLE_API_REJECTED",
                message=f"remote simple-api rejected certificate: {summary}",
                verdict=verdict,
                remote_url=remote_url,
                summary=summary,
                progress=progress,
            )
        if errors > 0:
            return raw_result_payload(
                run_id=run_id,
                status="error",
                error_code="REMOTE_SIMPLE_API_EVALUATOR_ERROR",
                message=f"remote simple-api evaluator error: {summary}",
                verdict=verdict,
                remote_url=remote_url,
                summary=summary,
                progress=progress,
            )
    return raw_result_payload(
        run_id=run_id,
        status=str(detail.get("status") or "error"),
        error_code="REMOTE_SIMPLE_API_NO_SUMMARY",
        message=f"remote simple-api run did not return usable one-problem summary: {detail}",
        verdict=verdict,
        remote_url=remote_url,
        summary=summary,
        progress=progress,
    )


def raw_result_payload(
    *,
    run_id: str | None,
    status: str,
    error_code: str,
    message: str,
    verdict: str | None = None,
    remote_url: str | None = None,
    summary: Any | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "error_code": error_code,
        "message": message,
        "stdout": "",
        "stderr": "" if status == "accepted" else message,
        "verdict": verdict,
        "artifact_path": remote_url,
        "direct_declarations": [],
        "axioms": [],
        "remote_simple_api": {
            "run_id": run_id,
            "url": remote_url,
            "summary": summary,
            "progress": progress,
        },
    }


def single_certificate_solver_text(*, verdict: str, code: str) -> str:
    verdict_literal = json.dumps(verdict, ensure_ascii=False)
    code_literal = json.dumps(code, ensure_ascii=False)
    return (
        "import json\n"
        "import sys\n\n"
        f"VERDICT = {verdict_literal}\n"
        f"CODE = {code_literal}\n\n"
        "def read_message():\n"
        "    line = sys.stdin.readline()\n"
        "    if not line:\n"
        "        sys.exit(0)\n"
        "    return json.loads(line)\n\n"
        "def send_message(message):\n"
        "    print(json.dumps(message), flush=True)\n\n"
        "def main():\n"
        "    read_message()\n"
        "    send_message({'call': 'judge', 'verdict': VERDICT, 'code': CODE})\n"
        "    response = read_message()\n"
        "    if response.get('status') == 'accepted':\n"
        "        return\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def simple_api_json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    parsed = json.loads(body or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{method} {url} returned non-object JSON")
    return parsed


def health_ok(base_url: str, timeout: int | None) -> bool:
    try:
        payload = simple_api_json_request(
            "GET",
            f"{base_url.rstrip('/')}/health",
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return False
    return payload.get("service") == "simple-api" and payload.get("status") == "ok"


def select_base_url(base_urls: Sequence[str], *, request_timeout_seconds: int) -> str:
    for base_url in normalize_base_urls(base_urls):
        if health_ok(base_url, request_timeout_seconds):
            return base_url
    raise RuntimeError("no healthy remote simple-api backend found: " + ", ".join(base_urls))


def normalize_base_urls(value: str | Sequence[str]) -> tuple[str, ...]:
    raw_urls = value.split(",") if isinstance(value, str) else list(value)
    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in raw_urls:
        url = str(raw_url).strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return tuple(urls)


def remote_run_id(prefix: str, problem: dict[str, Any], *, index: int) -> str:
    problem_id = str(problem.get("id") or f"problem-{index}")
    safe_problem_id = "".join(
        char if char.isalnum() or char in "_.-" else "-"
        for char in problem_id
    )
    safe_prefix = "".join(
        char if char.isalnum() or char in "_.-" else "-"
        for char in prefix
    )
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{index:02d}"
    return f"{safe_prefix}-{safe_problem_id}-{suffix}".strip(".-")[:128]


if __name__ == "__main__":
    raise SystemExit(main())
