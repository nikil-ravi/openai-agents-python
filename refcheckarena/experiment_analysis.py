"""Analyze RefCheckArena result JSON files into paper-facing tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # pragma: no cover - direct script execution.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from refcheckarena.refcheckarena_arena import AGENTS, DIMENSIONS

BENCHMARK_SOURCE = "https://openai.com/index/gpt-4-1/"


BENCHMARKS: dict[str, dict[str, float | str]] = {
    "openai/gpt-4o-mini-2024-07-18": {
        "label": "GPT-4o mini",
        "mmlu": 82.0,
        "gpqa": 40.2,
        "swe_bench_verified": 8.7,
        "ifeval": 78.4,
        "multichallenge": 20.3,
        "complex_func_bench": 38.6,
        "tau_bench_airline": 22.0,
        "tau_bench_retail": 44.0,
    },
    "openai/gpt-4.1-mini-2025-04-14": {
        "label": "GPT-4.1 mini",
        "mmlu": 87.5,
        "gpqa": 65.0,
        "swe_bench_verified": 23.6,
        "ifeval": 84.1,
        "multichallenge": 35.8,
        "complex_func_bench": 49.3,
        "tau_bench_airline": 36.0,
        "tau_bench_retail": 55.8,
    },
    "openai/gpt-4.1-2025-04-14": {
        "label": "GPT-4.1",
        "mmlu": 90.2,
        "gpqa": 66.3,
        "swe_bench_verified": 54.6,
        "ifeval": 87.4,
        "multichallenge": 38.3,
        "complex_func_bench": 65.5,
        "tau_bench_airline": 49.4,
        "tau_bench_retail": 68.0,
    },
}


@dataclass
class ResultRow:
    """Flattened result for one task/condition run."""

    file: str
    run_label: str
    profile: str
    model: str
    checker_model: str
    model_profile: str
    context_mode: str
    critic_min_revision: str
    condition: str
    collaboration_profile: str
    reference_limit: int
    reference_mode: str
    task: str
    turns: int
    artifacts: int
    reviews: int
    critic_rejections: int
    handoffs: int
    open_handoffs: int
    handoff_completion_rate: float
    checks: int
    timeouts: int
    insufficient_rate: float | None
    citation_rate: float | None
    avg_confidence: float | None
    avg_evidence_items: float | None
    score_spread: float | None
    received_overall: float | None
    received_dimensions: dict[str, float | None]


def load_rows(paths: list[Path]) -> list[ResultRow]:
    rows: list[ResultRow] = []
    expected_full_checks = len(AGENTS) * (len(AGENTS) - 1)
    for path in paths:
        payload = json.loads(path.read_text())
        config = payload.get("run_config", {})
        reference_limit = int(config.get("reference_limit") or 0)
        reference_mode = (
            "full"
            if reference_limit == 0 or reference_limit >= expected_full_checks
            else f"sampled_{reference_limit}"
        )
        for result in payload["results"]:
            health = result["health"]
            evidence = result["aggregate"]["evidence"]
            received_dimensions = average_received_dimensions(result)
            rows.append(
                ResultRow(
                    file=path.name,
                    run_label=config.get("run_label") or "",
                    profile=config.get("profile") or "unknown",
                    model=config.get("model") or "unknown",
                    checker_model=config.get("checker_model") or "unknown",
                    model_profile=config.get("model_profile") or "homogeneous",
                    context_mode=config.get("context_mode") or result.get("context_mode", "full"),
                    critic_min_revision=str(config.get("critic_min_revision", "unknown")),
                    condition=result["condition"],
                    collaboration_profile=config.get("collaboration_profile") or "unknown",
                    reference_limit=reference_limit,
                    reference_mode=reference_mode,
                    task=result["task"]["title"],
                    turns=health["turn_count"],
                    artifacts=health["artifact_count"],
                    reviews=health["review_count"],
                    critic_rejections=health["critic_rejection_count"],
                    handoffs=health["handoff_count"],
                    open_handoffs=health["open_handoff_count"],
                    handoff_completion_rate=health["handoff_completion_rate"],
                    checks=evidence["checks"],
                    timeouts=len(result.get("reference_timeouts", [])),
                    insufficient_rate=evidence["insufficient_rate"],
                    citation_rate=evidence["citation_rate"],
                    avg_confidence=evidence["avg_confidence"],
                    avg_evidence_items=evidence["avg_items"],
                    score_spread=overall_score_spread(result),
                    received_overall=received_dimensions["overall"],
                    received_dimensions=received_dimensions,
                )
            )
    return rows


def average_received_dimensions(result: dict[str, Any]) -> dict[str, float | None]:
    dims: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
    for scores in result["aggregate"]["received"].values():
        for dimension in DIMENSIONS:
            value = scores.get(dimension)
            if value is not None:
                dims[dimension].append(float(value))
    return {
        dimension: sum(values) / len(values) if values else None
        for dimension, values in dims.items()
    }


def overall_score_spread(result: dict[str, Any]) -> float | None:
    values: list[float] = []
    for scores in result["aggregate"]["received"].values():
        value = scores.get("overall")
        if value is not None:
            values.append(float(value))
    return max(values) - min(values) if values else None


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def grouped_means(rows: list[ResultRow], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[ResultRow]] = defaultdict(list)
    for row in rows:
        groups[tuple(getattr(row, key) for key in keys)].append(row)
    output: list[dict[str, Any]] = []
    for group_key, group_rows in sorted(groups.items()):
        record = dict(zip(keys, group_key))
        record.update(
            {
                "n": len(group_rows),
                "turns": mean([float(row.turns) for row in group_rows]),
                "artifacts": mean([float(row.artifacts) for row in group_rows]),
                "reviews": mean([float(row.reviews) for row in group_rows]),
                "critic_rejections": mean([float(row.critic_rejections) for row in group_rows]),
                "handoffs": mean([float(row.handoffs) for row in group_rows]),
                "open_handoffs": mean([float(row.open_handoffs) for row in group_rows]),
                "checks": mean([float(row.checks) for row in group_rows]),
                "timeouts": mean([float(row.timeouts) for row in group_rows]),
                "insufficient_rate": mean(
                    [
                        float(row.insufficient_rate)
                        for row in group_rows
                        if row.insufficient_rate is not None
                    ]
                ),
                "citation_rate": mean(
                    [
                        float(row.citation_rate)
                        for row in group_rows
                        if row.citation_rate is not None
                    ]
                ),
                "avg_confidence": mean(
                    [
                        float(row.avg_confidence)
                        for row in group_rows
                        if row.avg_confidence is not None
                    ]
                ),
                "refcheck_overall": mean(
                    [
                        float(row.received_overall)
                        for row in group_rows
                        if row.received_overall is not None
                    ]
                ),
                "score_spread": mean(
                    [float(row.score_spread) for row in group_rows if row.score_spread is not None]
                ),
            }
        )
        for dimension in DIMENSIONS:
            dimension_values: list[float] = []
            for row in group_rows:
                value = row.received_dimensions[dimension]
                if value is not None:
                    dimension_values.append(float(value))
            record[dimension] = mean(dimension_values)
        output.append(record)
    return output


def benchmark_average(model: str) -> float | None:
    benchmark = BENCHMARKS.get(model)
    if not benchmark:
        return None
    keys = [key for key, value in benchmark.items() if isinstance(value, float)]
    values = [float(benchmark[key]) for key in keys]
    return sum(values) / len(values)


def benchmark_alignment(rows: list[ResultRow]) -> list[dict[str, Any]]:
    model_rows = [
        row
        for row in rows
        if row.condition == "structured"
        and row.collaboration_profile == "calibration"
        and row.critic_min_revision == "1"
        and row.context_mode == "compact"
        and row.profile != "recheck"
        and row.model in BENCHMARKS
        and row.received_overall is not None
    ]
    grouped = grouped_means(model_rows, ["model"])
    output: list[dict[str, Any]] = []
    for record in grouped:
        model = str(record["model"])
        benchmark = BENCHMARKS[model]
        benchmark_avg = benchmark_average(model)
        output.append(
            {
                "model": model,
                "label": benchmark["label"],
                "benchmark_avg": benchmark_avg,
                "academic_avg": mean([float(benchmark["mmlu"]), float(benchmark["gpqa"])]),
                "coding": benchmark["swe_bench_verified"],
                "instruction_avg": mean(
                    [float(benchmark["ifeval"]), float(benchmark["multichallenge"])]
                ),
                "tool_avg": mean(
                    [
                        float(benchmark["complex_func_bench"]),
                        float(benchmark["tau_bench_airline"]),
                        float(benchmark["tau_bench_retail"]),
                    ]
                ),
                "refcheck_overall": record["refcheck_overall"],
                "collaboration": record["collaboration"],
                "handoff_clarity": record["handoff_clarity"],
                "reliability": record["reliability"],
                "communication": record["communication"],
                "initiative": record["initiative"],
                "n": record["n"],
            }
        )
    output.sort(key=lambda row: float(row["benchmark_avg"] or 0), reverse=True)
    add_ranks(output, "benchmark_avg", "benchmark_rank")
    add_ranks(output, "refcheck_overall", "refcheck_rank")
    for row in output:
        row["rank_delta"] = row["benchmark_rank"] - row["refcheck_rank"]
    return output


def add_ranks(rows: list[dict[str, Any]], key: str, rank_key: str) -> None:
    ranked = sorted(rows, key=lambda row: float(row[key] or -math.inf), reverse=True)
    for index, row in enumerate(ranked, 1):
        row[rank_key] = index


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    return pearson(ranks(xs), ranks(ys))


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    out = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        rank = (i + 1 + j) / 2
        for k in range(i, j):
            out[indexed[k][0]] = rank
        i = j
    return out


def correlation_rows(alignment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for metric in ["refcheck_overall", "handoff_clarity", "reliability", "communication"]:
        paired = [
            (float(row["benchmark_avg"]), float(row[metric]))
            for row in alignment
            if row["benchmark_avg"] is not None and row[metric] is not None
        ]
        benchmark_values = [benchmark for benchmark, _ in paired]
        metric_values = [value for _, value in paired]
        output.append(
            {
                "metric": metric,
                "pearson_r": pearson(benchmark_values, metric_values),
                "spearman_rho": spearman(benchmark_values, metric_values),
                "n": len(metric_values),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    header = "|" + "|".join(columns) + "|"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = []
    for row in rows:
        body.append("|" + "|".join(format_cell(row.get(col)) for col in columns) + "|")
    return "\n".join([header, sep, *body])


def format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def svg_text(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_handoff_plot(path: Path, environment: list[dict[str, Any]]) -> None:
    """Write a compact SVG bar chart for handoff counts."""

    rows = [
        row
        for row in environment
        if row.get("model") != "unknown" and row.get("handoffs") is not None
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    width = 900
    height = 420
    margin_left = 90
    margin_bottom = 105
    plot_width = width - margin_left - 35
    plot_height = height - 65 - margin_bottom
    max_value = max(float(row["handoffs"]) for row in rows) or 1.0
    bar_width = plot_width / max(len(rows), 1) * 0.62
    step = plot_width / max(len(rows), 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="28" y="34" font-family="Arial" font-size="20" '
        'font-weight="700">Mean handoffs by condition</text>',
        f'<line x1="{margin_left}" y1="{height - margin_bottom}" '
        f'x2="{width - 30}" y2="{height - margin_bottom}" stroke="#222"/>',
        f'<line x1="{margin_left}" y1="60" x2="{margin_left}" '
        f'y2="{height - margin_bottom}" stroke="#222"/>',
    ]
    for tick in range(0, int(max_value) + 1, max(1, int(max_value // 4) or 1)):
        y = height - margin_bottom - (tick / max_value) * plot_height
        parts.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="Arial" font-size="12">{tick}</text>'
        )
        parts.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - 30}" y2="{y:.1f}" stroke="#ddd"/>'
        )
    for index, row in enumerate(rows):
        value = float(row["handoffs"])
        x = margin_left + index * step + (step - bar_width) / 2
        bar_height = (value / max_value) * plot_height
        y = height - margin_bottom - bar_height
        color = "#2f6f73" if row["condition"] == "structured" else "#a65d32"
        label = f"{row['condition']}\n{row['collaboration_profile']}\n{row['model']}".replace(
            "openai/", ""
        )
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" '
            f'text-anchor="middle" font-family="Arial" font-size="12">{value:.1f}</text>'
        )
        for line_index, line in enumerate(label.splitlines()):
            parts.append(
                f'<text x="{x + bar_width / 2:.1f}" '
                f'y="{height - margin_bottom + 20 + line_index * 15}" '
                'text-anchor="middle" font-family="Arial" font-size="11">'
                f"{svg_text(line)}</text>"
            )
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def write_benchmark_scatter(path: Path, alignment: list[dict[str, Any]]) -> None:
    """Write a compact SVG scatter plot for benchmark/refcheck alignment."""

    rows = [
        row
        for row in alignment
        if row.get("benchmark_avg") is not None and row.get("refcheck_overall") is not None
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    width = 720
    height = 470
    left = 80
    right = 35
    top = 55
    bottom = 75
    xs = [float(row["benchmark_avg"]) for row in rows]
    ys = [float(row["refcheck_overall"]) for row in rows]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    if y_min == y_max:
        y_min -= 0.5
        y_max += 0.5
    plot_w = width - left - right
    plot_h = height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="28" y="34" font-family="Arial" font-size="20" '
        'font-weight="700">Benchmark average vs RefCheck overall</text>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#222"/>',
        f'<text x="{width / 2}" y="{height - 20}" text-anchor="middle" '
        'font-family="Arial" font-size="13">Official benchmark average (%)</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" '
        'text-anchor="middle" font-family="Arial" font-size="13">RefCheck overall (1-5)</text>',
    ]
    for tick in range(5):
        x_value = x_min + (x_max - x_min) * tick / 4
        x = px(x_value)
        parts.append(
            f'<text x="{x:.1f}" y="{height - bottom + 20}" text-anchor="middle" '
            f'font-family="Arial" font-size="12">{x_value:.1f}</text>'
        )
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - bottom}" stroke="#eee"/>'
        )
        y_value = y_min + (y_max - y_min) * tick / 4
        y = py(y_value)
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-family="Arial" font-size="12">{y_value:.2f}</text>'
        )
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#eee"/>'
        )
    for row in rows:
        x = px(float(row["benchmark_avg"]))
        y = py(float(row["refcheck_overall"]))
        label = svg_text(row["label"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#2f6f73"/>')
        parts.append(
            f'<text x="{x + 11:.1f}" y="{y - 9:.1f}" font-family="Arial" '
            f'font-size="12">{label}</text>'
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def write_report(
    path: Path,
    rows: list[ResultRow],
    environment: list[dict[str, Any]],
    score_summary: list[dict[str, Any]],
    alignment: list[dict[str, Any]],
    correlations: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# RefCheckArena Experiment Report",
        "",
        "This report is generated from local JSON result files under `refcheckarena/results/`.",
        "",
        "## Scope",
        "",
        f"- Result rows analyzed: {len(rows)}",
        "- Reference-check matrix modes are reported in CSV outputs; `full` means all "
        f"{len(AGENTS) * (len(AGENTS) - 1)} ordered evaluator-target pairs were attempted.",
        f"- Benchmark source: OpenAI GPT-4.1 launch benchmark appendix ({BENCHMARK_SOURCE}).",
        "- Benchmark alignment uses GPT-4o mini, GPT-4.1 mini, and GPT-4.1 because "
        "those models have comparable scores in the same official table.",
        "- Benchmark alignment is filtered to compact, structured, forced-Critic calibration "
        "runs, excluding baseline, no-forced-Critic ablations, and checker-only rechecks.",
        "",
        "## Environment Health",
        "",
        markdown_table(
            environment,
            [
                "condition",
                "collaboration_profile",
                "model",
                "checker_model",
                "profile",
                "model_profile",
                "context_mode",
                "critic_min_revision",
                "reference_mode",
                "n",
                "turns",
                "artifacts",
                "reviews",
                "critic_rejections",
                "handoffs",
                "open_handoffs",
                "checks",
                "insufficient_rate",
                "citation_rate",
            ],
        ),
        "",
        "## Reference Score Summary",
        "",
        markdown_table(
            score_summary,
            [
                "condition",
                "collaboration_profile",
                "model",
                "checker_model",
                "profile",
                "model_profile",
                "context_mode",
                "critic_min_revision",
                "reference_mode",
                "n",
                "refcheck_overall",
                "collaboration",
                "handoff_clarity",
                "reliability",
                "communication",
                "initiative",
                "score_spread",
            ],
        ),
        "",
        "## Benchmark vs Reference-Check Alignment",
        "",
        markdown_table(
            alignment,
            [
                "label",
                "benchmark_avg",
                "academic_avg",
                "coding",
                "instruction_avg",
                "tool_avg",
                "refcheck_overall",
                "collaboration",
                "handoff_clarity",
                "reliability",
                "communication",
                "initiative",
                "benchmark_rank",
                "refcheck_rank",
                "rank_delta",
            ],
        ),
        "",
        "## Benchmark Correlations",
        "",
        markdown_table(correlations, ["metric", "pearson_r", "spearman_rho", "n"]),
        "",
        "## Generated Plots",
        "",
        "- `handoffs_by_condition.svg` shows mean handoff counts for each analyzed condition.",
        "- `benchmark_alignment.svg` plots official benchmark average against RefCheck overall.",
        "",
        "## Doubts and Caveats",
        "",
        "- Current live runs are still small. Treat correlations as pilot results until "
        "we add repeated runs and full reference matrices for every model.",
        "- The calibration profile deliberately seeds recoverable collaboration friction. "
        "It is useful for validating the instrument, but neutral-profile results should be "
        "reported separately as the main condition.",
        "- Reference checks are LLM-generated. The target-specific summaries reduce generic "
        "team praise, but a human or cross-model rater panel would strengthen claims.",
        "- Benchmark alignment uses public benchmark percentages from one OpenAI source. "
        "This is clean for a pilot table, but the paper should clearly describe it as a "
        "coarse capability index rather than a definitive leaderboard.",
        "- Full ordered-pair checks are more rigorous than sampled checks. Any table that "
        "uses sampled checks should say so explicitly.",
        "- GPT-5.4/GPT-5.5 collaboration-generation attempts through Vals were materially "
        "slower than GPT-4.1 mini in this local environment. Completed GPT-5-family data in "
        "this report should be read as checker-only unless the `model` column itself is a "
        "GPT-5-family model.",
        "",
    ]
    path.write_text("\n".join(lines))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("refcheckarena/analysis"))
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    rows = load_rows(args.results)
    environment = grouped_means(
        rows,
        [
            "condition",
            "collaboration_profile",
            "model",
            "checker_model",
            "profile",
            "model_profile",
            "context_mode",
            "critic_min_revision",
            "reference_mode",
        ],
    )
    score_summary = grouped_means(
        rows,
        [
            "condition",
            "collaboration_profile",
            "model",
            "checker_model",
            "profile",
            "model_profile",
            "context_mode",
            "critic_min_revision",
            "reference_mode",
        ],
    )
    alignment = benchmark_alignment(rows)
    correlations = correlation_rows(alignment)

    out = args.output_dir
    write_csv(out / "environment_health.csv", environment)
    write_csv(out / "score_summary.csv", score_summary)
    write_csv(out / "benchmark_alignment.csv", alignment)
    write_csv(out / "benchmark_correlations.csv", correlations)
    write_handoff_plot(out / "handoffs_by_condition.svg", environment)
    write_benchmark_scatter(out / "benchmark_alignment.svg", alignment)
    write_report(
        out / "experiment_report.md",
        rows,
        environment,
        score_summary,
        alignment,
        correlations,
    )
    print(f"Wrote analysis to {out}")


if __name__ == "__main__":
    main()
