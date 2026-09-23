"""Command line entry point: run / report / recompute / compare, plus batches and
ingest for runs answered by subagents."""
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
    run_p.add_argument("--suite", default="chain", choices=["chain", "arith", "mult", "jsonl"])
    run_p.add_argument("--suite-path", default=None, help="path to a .jsonl task file (suite=jsonl)")
    run_p.add_argument("--depth", type=int, default=8, help="chain suite difficulty")
    run_p.add_argument("--digits", type=int, default=6, help="mult suite difficulty")
    run_p.add_argument("--trials", type=int, default=20)
    run_p.add_argument("--sizes", type=_parse_sizes, default=[1, 2, 3, 4, 5])
    run_p.add_argument("--topology", default="independent", choices=["independent", "debate"])
    run_p.add_argument("--seed", type=int, default=7)
    run_p.add_argument("--out", required=True, help="run directory for transcripts and results")
    run_p.add_argument("--resume", action="store_true", help="continue a killed run in --out")
    run_p.add_argument("--workers", type=int, default=1, help="parallel calls within a round")
    run_p.add_argument("--mock", action="store_true", help="no API: deterministic fake model")
    run_p.add_argument("--mock-accuracy", type=float, default=0.65)
    run_p.add_argument(
        "--mock-correlation", type=float, default=0.0,
        help="mock only: 0..1, how often agents share a mistake (0 = independent)",
    )
    run_p.add_argument(
        "--subagents", default=None, metavar="LABEL",
        help="no API: answers come from subagents via batches/ingest; LABEL names them "
        "in the manifest, e.g. nagents-solver(sonnet,effort=low)",
    )
    run_p.add_argument("--model", default=None, help="Claude model id (default claude-opus-5)")
    run_p.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    run_p.add_argument("--max-tokens", type=int, default=16000)

    rep_p = sub.add_parser("report", help="print the report for a finished run")
    rep_p.add_argument("run_dir", help="run directory (holds results.json)")
    rep_p.add_argument("--html", action="store_true", help="also write charts/ and report.html")

    rec_p = sub.add_parser("recompute", help="rebuild results.json from the trial transcripts")
    rec_p.add_argument("run_dir", help="run directory (holds manifest.json + trials/)")

    cmp_p = sub.add_parser("compare", help="compare two finished runs size by size")
    cmp_p.add_argument("run_a")
    cmp_p.add_argument("run_b")
    cmp_p.add_argument("--chart", default=None, metavar="SVG", help="also draw both curves to this file")

    bat_p = sub.add_parser("batches", help="split a subagent run's pending calls into batches")
    bat_p.add_argument("run_dir")
    bat_p.add_argument("--per-batch", type=int, default=10, help="problems per subagent")
    bat_p.add_argument(
        "--prompts", default=None, metavar="DIR",
        help="also write each batch's exact subagent message to DIR/<batch>.txt",
    )

    ing_p = sub.add_parser("ingest", help="store subagent replies for a run's pending calls")
    ing_p.add_argument("run_dir")
    ing_p.add_argument("reply_files", nargs="+", help="text files holding subagent replies")

    args = parser.parse_args(argv)

    from .report import render

    if args.command == "report":
        results = json.loads(
            (Path(args.run_dir) / "results.json").read_text(encoding="utf-8")
        )
        print(render(results))
        if args.html:
            _write_visuals(results, args.run_dir)
        return 0

    if args.command == "recompute":
        from .runner import recompute

        results = recompute(args.run_dir)
        print(render(results))
        _write_visuals(results, args.run_dir)
        return 0

    if args.command == "compare":
        from .compare import compare

        print(compare(args.run_a, args.run_b, chart=args.chart))
        return 0

    if args.command == "batches":
        from .external import batch_prompt, make_batches

        batches = make_batches(args.run_dir, per_batch=args.per_batch)
        if args.prompts:
            out = Path(args.prompts)
            out.mkdir(parents=True, exist_ok=True)
            for b in batches:
                (out / f"{b['batch']}.txt").write_text(batch_prompt(b), encoding="utf-8")
        calls = sum(len(b["items"]) for b in batches)
        print(f"{len(batches)} batch(es), {calls} call(s) -> {args.run_dir}/batches.json")
        return 0

    if args.command == "ingest":
        from .external import ingest

        total_added = 0
        for name in args.reply_files:
            stats = ingest(args.run_dir, Path(name).read_text(encoding="utf-8"), source=Path(name).name)
            total_added += stats["added"]
            note = f", {len(stats['unknown'])} unknown id(s) ignored" if stats["unknown"] else ""
            print(f"{name}: {stats['parsed']} parsed, {stats['added']} stored{note}")
        print(f"Stored {total_added} new answer(s). Rerun the same 'nagents run' command with --resume.")
        return 0

    from .models import DEFAULT_MODEL, AnthropicModel, MockModel
    from .runner import run_grid
    from .tasks import make_suite

    if args.mock and args.subagents:
        parser.error("--mock and --subagents are exclusive")
    if args.mock:
        model = MockModel(accuracy=args.mock_accuracy, correlation=args.mock_correlation)
        model_label = f"mock(accuracy={args.mock_accuracy})"
        if args.mock_correlation:
            model_label = f"mock(accuracy={args.mock_accuracy}, correlation={args.mock_correlation})"
    elif args.subagents:
        from .external import ExternalModel

        Path(args.out).mkdir(parents=True, exist_ok=True)
        model = ExternalModel(args.out)
        model_label = f"subagents:{args.subagents}"
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
        "model": None if (args.mock or args.subagents) else (args.model or DEFAULT_MODEL),
        "effort": args.effort,
        "max_tokens": args.max_tokens,
    }
    # New keys only when used, so runs from older versions still --resume.
    if args.mock and args.mock_correlation:
        extra_config["mock_correlation"] = args.mock_correlation
    if args.subagents:
        extra_config["subagents"] = args.subagents
    if args.suite == "mult":
        extra_config["digits"] = args.digits

    from .external import PendingAnswers

    tasks = make_suite(
        args.suite, args.trials, args.seed, depth=args.depth, path=args.suite_path, digits=args.digits
    )
    try:
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
    except PendingAnswers as waiting:
        print(
            f"Waiting on subagents: {waiting}.\n"
            f"Pending calls: {waiting.path}\n"
            f"Next: nagents batches {args.out}, answer each batch, "
            f"nagents ingest {args.out} <reply files>, then rerun this command with --resume."
        )
        return 3
    print(render(results))
    _write_visuals(results, args.out)
    print(
        f"\nTranscripts: {args.out}/trials/   Results: {args.out}/results.json   "
        f"Report: {args.out}/report.html"
    )
    return 0


def _write_visuals(results: dict, run_dir) -> None:
    from .charts import write_charts
    from .html import write_html

    write_charts(results, run_dir)
    write_html(results, run_dir)
