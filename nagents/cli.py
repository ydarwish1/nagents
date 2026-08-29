"""Command line entry point: nagents run / report / recompute."""
import argparse
import json
from pathlib import Path


def _parse_sizes(text: str):
    sizes = sorted({int(part) for part in text.split(",") if part.strip()})
    if not sizes or sizes[0] < 1:
        raise argparse.ArgumentTypeError("sizes must be positive integers, e.g. 1,2,3,5")
    return sizes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="nagents", description="Do more agents actually help? Measured."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one grid: same tasks, every group size")
    run_p.add_argument("--suite", default="chain", choices=["chain", "arith", "jsonl"])
    run_p.add_argument("--suite-path", default=None, help="path to a .jsonl task file (suite=jsonl)")
    run_p.add_argument("--depth", type=int, default=8, help="chain suite difficulty")
    run_p.add_argument("--trials", type=int, default=20)
    run_p.add_argument("--sizes", type=_parse_sizes, default=[1, 2, 3, 4, 5])
    run_p.add_argument("--topology", default="independent", choices=["independent", "debate"])
    run_p.add_argument("--seed", type=int, default=7)
    run_p.add_argument("--out", required=True, help="run directory for transcripts and results")
    run_p.add_argument("--resume", action="store_true", help="continue a killed run in --out")
    run_p.add_argument("--workers", type=int, default=1, help="parallel calls within a round")
    run_p.add_argument("--mock", action="store_true", help="no API: deterministic fake model")
    run_p.add_argument("--mock-accuracy", type=float, default=0.65)
    run_p.add_argument("--model", default=None, help="Claude model id (default claude-opus-5)")
    run_p.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    run_p.add_argument("--max-tokens", type=int, default=16000)

    rep_p = sub.add_parser("report", help="print the report for a finished run")
    rep_p.add_argument("run_dir", help="run directory (holds results.json)")

    rec_p = sub.add_parser("recompute", help="rebuild results.json from the trial transcripts")
    rec_p.add_argument("run_dir", help="run directory (holds manifest.json + trials/)")

    args = parser.parse_args(argv)

    from .report import render

    if args.command == "report":
        results = json.loads(
            (Path(args.run_dir) / "results.json").read_text(encoding="utf-8")
        )
        print(render(results))
        return 0

    if args.command == "recompute":
        from .runner import recompute

        print(render(recompute(args.run_dir)))
        return 0

    from .models import DEFAULT_MODEL, AnthropicModel, MockModel
    from .runner import run_grid
    from .tasks import make_suite

    if args.mock:
        model = MockModel(accuracy=args.mock_accuracy)
        model_label = f"mock(accuracy={args.mock_accuracy})"
    else:
        model_id = args.model or DEFAULT_MODEL
        model = AnthropicModel(model=model_id, max_tokens=args.max_tokens, effort=args.effort)
        model_label = model_id

    # Everything that can change results belongs here — it is what --resume
    # checks against the run directory's manifest.
    extra_config = {
        "suite": args.suite,
        "suite_path": args.suite_path,
        "depth": args.depth,
        "mock": args.mock,
        "mock_accuracy": args.mock_accuracy if args.mock else None,
        "model": None if args.mock else (args.model or DEFAULT_MODEL),
        "effort": args.effort,
        "max_tokens": args.max_tokens,
    }

    tasks = make_suite(args.suite, args.trials, args.seed, depth=args.depth, path=args.suite_path)
    results = run_grid(
        model,
        tasks,
        args.sizes,
        args.topology,
        args.seed,
        args.out,
        model_label,
        workers=args.workers,
        resume=args.resume,
        extra_config=extra_config,
    )
    print(render(results))
    print(f"\nTranscripts: {args.out}/trials/   Results: {args.out}/results.json")
    return 0
