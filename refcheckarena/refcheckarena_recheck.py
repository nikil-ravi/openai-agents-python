"""Rerun peer reference checks on saved RefCheckArena collaboration traces."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - direct script execution.
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from refcheckarena.refcheckarena_arena import (
    DEFAULT_CHECKER_MODEL,
    FakeModelClient,
    ModelClient,
    TimeoutRetryModelClient,
    ValsModelClient,
    aggregate,
    collect_reference_checks,
    ordered_reference_pairs,
    save_results,
    state_from_dict,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path)
    parser.add_argument("--client", choices=["vals", "fake"], default="vals")
    parser.add_argument("--checker-model", default=DEFAULT_CHECKER_MODEL)
    parser.add_argument(
        "--result-index",
        type=int,
        default=None,
        help="Zero-based result row to recheck. Omit to recheck all rows.",
    )
    parser.add_argument(
        "--reference-limit",
        type=int,
        default=8,
        help="Number of ordered peer checks to run. Use 0 for all pairs.",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--reference-timeout", type=float, default=180.0)
    parser.add_argument("--model-timeout", type=float, default=180.0)
    parser.add_argument("--model-retries", type=int, default=1)
    parser.add_argument("--run-label", default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("refcheckarena/results"))
    return parser


def selected_rows(payload: dict[str, object], result_index: int | None) -> list[dict[str, object]]:
    results = payload["results"]
    if not isinstance(results, list):
        raise ValueError("Result JSON must contain a list at key 'results'.")
    if result_index is None:
        return results
    if result_index < 0 or result_index >= len(results):
        raise ValueError(f"--result-index must be between 0 and {len(results) - 1}")
    return [results[result_index]]


async def run_recheck(args: argparse.Namespace) -> Path:
    payload = json.loads(args.result_json.read_text())
    rows = selected_rows(payload, args.result_index)

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"[refcheckarena] {message}", flush=True)

    client: ModelClient
    close_client = None
    if args.client == "fake":
        client = FakeModelClient()
    else:
        vals_client = ValsModelClient(Path(".env"))
        client = vals_client
        close_client = vals_client.aclose
    client = TimeoutRetryModelClient(
        client,
        timeout_seconds=args.model_timeout,
        attempts=args.model_retries,
        progress=progress,
    )

    output_rows: list[dict[str, object]] = []
    try:
        for row in rows:
            state = state_from_dict(row)
            contributors = list(state.health_metrics()["contributors"])
            pair_count = len(ordered_reference_pairs(contributors))
            if args.reference_limit > 0:
                pair_count = min(pair_count, args.reference_limit)
            progress(
                f"rechecking {state.condition} | {state.task.title} with "
                f"{args.checker_model}; collecting {pair_count} checks"
            )
            checks, timeouts = await collect_reference_checks(
                state,
                client,
                checker_model=args.checker_model,
                reference_limit=args.reference_limit,
                concurrency=args.concurrency,
                timeout_seconds=args.reference_timeout,
                progress=progress,
            )
            output_rows.append(
                {
                    "state": state,
                    "checks": checks,
                    "reference_timeouts": timeouts,
                    "aggregate": aggregate(
                        checks,
                        valid_turn_ids={turn.id for turn in state.turns},
                    ),
                }
            )
    finally:
        if close_client is not None:
            await close_client()

    original_config = payload.get("run_config", {})
    run_config = {
        "run_label": args.run_label,
        "client": args.client,
        "profile": "recheck",
        "collaboration_profile": original_config.get("collaboration_profile", "unknown")
        if isinstance(original_config, dict)
        else "unknown",
        "context_mode": original_config.get("context_mode", "unknown")
        if isinstance(original_config, dict)
        else "unknown",
        "model_profile": original_config.get("model_profile", "unknown")
        if isinstance(original_config, dict)
        else "unknown",
        "model": original_config.get("model", "unknown")
        if isinstance(original_config, dict)
        else "unknown",
        "agent_models": original_config.get("agent_models", {})
        if isinstance(original_config, dict)
        else {},
        "checker_model": args.checker_model,
        "source_result_json": str(args.result_json),
        "source_result_index": args.result_index,
        "reference_limit": args.reference_limit,
        "concurrency": args.concurrency,
        "reference_timeout": args.reference_timeout,
        "model_timeout": args.model_timeout,
        "model_retries": args.model_retries,
    }
    return save_results(output_rows, args.output_dir, run_config)


def main() -> None:
    args = build_arg_parser().parse_args()
    path = asyncio.run(run_recheck(args))
    print(f"\nSaved recheck results to {path}")


if __name__ == "__main__":
    main()
