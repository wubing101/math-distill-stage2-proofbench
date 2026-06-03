from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
VERSIONS = {
    "residual-1000-v1": "residual1000_v1_",
    "residual-1000-v2": "residual1000_v2_",
    "residual-1000-v3": "residual1000_v3_",
}
COLORS = {
    "residual-1000-v1": "#166a72",
    "residual-1000-v2": "#c94b36",
    "residual-1000-v3": "#3d5aa9",
}
LABELS = {
    "residual-1000-v1": "v1",
    "residual-1000-v2": "v2",
    "residual-1000-v3": "v3",
}
X_BREAK_HOURS = 12.0
X_TAIL_COMPRESSION = 0.10
X_MAIN_TICK_STEP = 2
X_TAIL_TICKS = [24, 36, 48, 60, 72, 84]


@dataclass(frozen=True)
class AcceptedEvent:
    version: str
    problem_id: str
    timestamp: datetime
    verdict: str
    source_file: Path
    line: int
    time_source: str


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot cumulative accepted progress for residual-1000 v1/v2/v3."
    )
    parser.add_argument("--runs-root", type=Path, default=Path("artifacts/proofbench_runs"))
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=Path("artifacts/progress_charts/residual1000_versions_accepted_progress.csv"),
    )
    parser.add_argument(
        "--svg-output",
        type=Path,
        action="append",
        default=[
            Path("artifacts/progress_charts/residual1000_versions_accepted_progress.svg"),
            Path("artifacts/progress_charts/residual1000_versions_accepted_progress_compressed.svg"),
            Path("artifacts/progress_charts/residual1000_versions_accepted_progress_12_84_compressed.svg"),
            Path("docs/assets/residual1000_versions_accepted_progress.svg"),
            Path("docs/assets/residual1000_versions_accepted_progress_compressed.svg"),
            Path("docs/assets/residual1000_versions_accepted_progress_12_84_compressed.svg"),
        ],
        help="SVG output path. May be passed more than once.",
    )
    return parser


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError:
                continue


def nested(row: dict, *keys: str):
    current = row
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def row_problem_id(row: dict) -> str:
    return str(
        row.get("id")
        or nested(row, "candidate_metadata", "id")
        or nested(row, "problem", "id")
        or ""
    )


def row_version(problem_id: str) -> str | None:
    for version, prefix in VERSIONS.items():
        if problem_id.startswith(prefix):
            return version
    return None


def row_status(row: dict) -> str:
    return str(row.get("status") or nested(row, "remote_result", "status") or "")


def row_verdict(row: dict) -> str:
    return str(
        row.get("verdict")
        or nested(row, "remote_result", "verdict")
        or nested(row, "answer", "verdict")
        or ""
    )


def parse_created_at(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    except ValueError:
        return None


def matching_input_path(result_path: Path) -> Path | None:
    candidate = result_path.with_name(result_path.name.replace("judge_results", "judge_input", 1))
    if candidate.exists():
        return candidate
    inputs = sorted(result_path.parent.glob("judge_input*.jsonl"))
    if len(inputs) == 1:
        return inputs[0]
    return None


def file_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=LOCAL_TZ)


def row_timestamp(row: dict, result_path: Path) -> tuple[datetime, str]:
    created_at = parse_created_at(nested(row, "remote_result", "remote_simple_api", "summary", "createdAt"))
    if created_at is not None:
        return created_at, "remote_result.remote_simple_api.summary.createdAt"

    created_at = parse_created_at(nested(row, "remote_result", "summary", "createdAt"))
    if created_at is not None:
        return created_at, "remote_result.summary.createdAt"

    input_path = matching_input_path(result_path)
    if input_path is not None:
        return file_timestamp(input_path), input_path.as_posix()
    return file_timestamp(result_path), result_path.as_posix()


def scan_runs(runs_root: Path) -> tuple[dict[str, list[AcceptedEvent]], dict[str, datetime]]:
    starts: dict[str, datetime] = {}
    first_accepts: dict[str, dict[str, AcceptedEvent]] = {version: {} for version in VERSIONS}

    for result_path in sorted(runs_root.rglob("judge_results*.jsonl")):
        for line_no, row in read_jsonl(result_path):
            if not isinstance(row, dict):
                continue
            problem_id = row_problem_id(row)
            version = row_version(problem_id)
            if version is None:
                continue

            timestamp, time_source = row_timestamp(row, result_path)
            starts[version] = min(starts.get(version, timestamp), timestamp)

            if row_status(row) != "accepted":
                continue
            event = AcceptedEvent(
                version=version,
                problem_id=problem_id,
                timestamp=timestamp,
                verdict=row_verdict(row),
                source_file=result_path,
                line=line_no,
                time_source=time_source,
            )
            previous = first_accepts[version].get(problem_id)
            if previous is None or (event.timestamp, event.source_file.as_posix(), event.line) < (
                previous.timestamp,
                previous.source_file.as_posix(),
                previous.line,
            ):
                first_accepts[version][problem_id] = event

    events_by_version: dict[str, list[AcceptedEvent]] = {}
    for version, events in first_accepts.items():
        events_by_version[version] = sorted(
            events.values(), key=lambda event: (event.timestamp, event.problem_id)
        )
    return events_by_version, starts


def local_timestamp(timestamp: datetime) -> str:
    local = timestamp.astimezone(LOCAL_TZ)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} CST"


def write_csv(path: Path, events_by_version: dict[str, list[AcceptedEvent]], starts: dict[str, datetime]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "version",
                "accepted_count",
                "new_id",
                "elapsed_hours",
                "timestamp_local",
                "verdict",
                "source_file",
                "line",
                "time_source",
            ],
        )
        writer.writeheader()
        for version in VERSIONS:
            start = starts[version]
            for count, event in enumerate(events_by_version[version], 1):
                elapsed = (event.timestamp - start).total_seconds() / 3600
                writer.writerow(
                    {
                        "version": version,
                        "accepted_count": count,
                        "new_id": event.problem_id,
                        "elapsed_hours": f"{elapsed:.4f}",
                        "timestamp_local": local_timestamp(event.timestamp),
                        "verdict": event.verdict,
                        "source_file": event.source_file.as_posix(),
                        "line": event.line,
                        "time_source": event.time_source,
                    }
                )


def compressed_elapsed(elapsed: float) -> float:
    if elapsed <= X_BREAK_HOURS:
        return elapsed
    return X_BREAK_HOURS + (elapsed - X_BREAK_HOURS) * X_TAIL_COMPRESSION


def svg_path_for_events(
    events: list[AcceptedEvent],
    start: datetime,
    x_scale,
    y_scale,
    plot_left: float,
    plot_bottom: float,
) -> str:
    parts = [f"M {plot_left:.1f} {plot_bottom:.1f}"]
    current_count = 0
    current_x = 0.0
    for count, event in enumerate(events, 1):
        elapsed = max(0.0, (event.timestamp - start).total_seconds() / 3600)
        x = x_scale(elapsed)
        y_prev = y_scale(current_count)
        y = y_scale(count)
        if x != current_x:
            parts.append(f"L {x:.1f} {y_prev:.1f}")
        parts.append(f"L {x:.1f} {y:.1f}")
        current_count = count
        current_x = x
    return " ".join(parts)


def render_svg(events_by_version: dict[str, list[AcceptedEvent]], starts: dict[str, datetime]) -> str:
    width, height = 1200, 760
    plot_left, plot_top, plot_right, plot_bottom = 100, 95, 1130, 625
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    max_elapsed = 0.0
    for version, events in events_by_version.items():
        if events:
            elapsed = (events[-1].timestamp - starts[version]).total_seconds() / 3600
            max_elapsed = max(max_elapsed, elapsed)
    raw_x_max = max(max_elapsed, X_BREAK_HOURS)
    if raw_x_max > X_BREAK_HOURS:
        raw_x_max = max(raw_x_max, X_TAIL_TICKS[-1])
    x_max = compressed_elapsed(raw_x_max)
    y_max = 1000

    def x_scale(elapsed: float) -> float:
        return plot_left + (compressed_elapsed(elapsed) / x_max) * plot_width

    def y_scale(count: int | float) -> float:
        return plot_bottom - (count / y_max) * plot_height

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="residual-1000 accepted count by version over elapsed hours">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,&quot;Segoe UI&quot;,Arial,sans-serif;fill:#252525}.title{font-size:30px;font-weight:700}.subtitle{font-size:16px;fill:#555}.small{font-size:16px;fill:#565656}.tick{font-size:14px;fill:#606060}.axis{stroke:#222;stroke-width:2}.grid{stroke:#deded8;stroke-width:1}.target{stroke:#a35b00;stroke-width:2;stroke-dasharray:8 8}.series{fill:none;stroke-width:4;stroke-linejoin:round;stroke-linecap:round}.legendbox{fill:#fff;stroke:#d0d0ca;stroke-width:1.2;rx:6}</style>",
        '<text class="title" x="100" y="42">residual-1000 accepted progress</text>',
        '<text class="subtitle" x="100" y="68">Cumulative first judge-accepted certificates; 12-84h is compressed to keep early trends readable.</text>',
    ]

    for y_tick in range(0, y_max + 1, 100):
        y = y_scale(y_tick)
        lines.append(f'<line class="grid" x1="{plot_left}" y1="{y:.1f}" x2="{plot_right}" y2="{y:.1f}"/>')
        lines.append(f'<text class="tick" x="86" y="{y + 5:.1f}" text-anchor="end">{y_tick}</text>')

    tick = 0
    while tick <= X_BREAK_HOURS:
        x = x_scale(tick)
        lines.append(f'<line class="grid" x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bottom}"/>')
        lines.append(f'<text class="tick" x="{x:.1f}" y="653" text-anchor="middle">{tick:g}</text>')
        tick += X_MAIN_TICK_STEP

    for tick in X_TAIL_TICKS:
        if tick <= raw_x_max + 1:
            x = x_scale(tick)
            lines.append(f'<line class="grid" x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bottom}"/>')
            lines.append(f'<text class="tick" x="{x:.1f}" y="653" text-anchor="middle">{tick:g}</text>')

    target_y = y_scale(1000)
    lines.extend(
        [
            f'<line class="target" x1="{plot_left}" y1="{target_y:.1f}" x2="{plot_right}" y2="{target_y:.1f}"/>',
            f'<text class="small" x="{plot_right - 8}" y="{target_y + 22:.1f}" text-anchor="end" fill="#8a4d00">1000 target</text>',
            f'<line class="axis" x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_bottom}"/>',
            f'<line class="axis" x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}"/>',
        ]
    )

    break_x = x_scale(X_BREAK_HOURS)
    lines.extend(
        [
            f'<line x1="{break_x - 9:.1f}" y1="{plot_bottom + 9}" x2="{break_x - 2:.1f}" y2="{plot_bottom - 9}" stroke="#222" stroke-width="2"/>',
            f'<line x1="{break_x + 2:.1f}" y1="{plot_bottom + 9}" x2="{break_x + 9:.1f}" y2="{plot_bottom - 9}" stroke="#222" stroke-width="2"/>',
            f'<text class="tick" x="{break_x + 15:.1f}" y="{plot_bottom - 18}" fill="#606060">12-84h compressed</text>',
        ]
    )

    for version in VERSIONS:
        path = svg_path_for_events(events_by_version[version], starts[version], x_scale, y_scale, plot_left, plot_bottom)
        lines.append(f'<path class="series" d="{path}" stroke="{COLORS[version]}"/>')

    legend_x, legend_y = 790, 335
    lines.append(f'<rect class="legendbox" x="{legend_x}" y="{legend_y}" width="255" height="132" rx="6"/>')
    for index, version in enumerate(VERSIONS):
        events = events_by_version[version]
        final_count = len(events)
        final_elapsed = (events[-1].timestamp - starts[version]).total_seconds() / 3600 if events else 0.0
        y = legend_y + 28 + index * 38
        color = COLORS[version]
        lines.append(f'<line x1="{legend_x + 18}" y1="{y - 5}" x2="{legend_x + 58}" y2="{y - 5}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
        lines.append(
            f'<text x="{legend_x + 72}" y="{y}" font-size="17" font-weight="700">{escape(LABELS[version])}: {final_count} accepted</text>'
        )
        lines.append(f'<text class="tick" x="{legend_x + 72}" y="{y + 18}">last new at {final_elapsed:.1f}h</text>')

    lines.extend(
        [
            '<text class="small" x="615" y="694" text-anchor="middle">Elapsed hours (12-84h compressed)</text>',
            '<text class="small" transform="translate(30 360) rotate(-90)" text-anchor="middle">Accepted count</text>',
            '<text class="tick" x="100" y="730">Source: local artifacts/proofbench_runs judge_results*.jsonl; duplicates counted once by first accepted problem id.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines)


def write_svgs(paths: list[Path], svg: str) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    events_by_version, starts = scan_runs(args.runs_root)
    missing = [version for version in VERSIONS if version not in starts]
    if missing:
        raise SystemExit(f"Missing judge result data for: {', '.join(missing)}")

    write_csv(args.csv_output, events_by_version, starts)
    write_svgs(args.svg_output, render_svg(events_by_version, starts))

    for version in VERSIONS:
        events = events_by_version[version]
        elapsed = (events[-1].timestamp - starts[version]).total_seconds() / 3600 if events else 0.0
        print(f"{version}: {len(events)} accepted, last new accepted at {elapsed:.2f}h")
    print(f"csv: {args.csv_output}")
    for path in args.svg_output:
        print(f"svg: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
