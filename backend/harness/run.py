"""CLI: python -m harness [CORPUS_DIR] [options]

Each model runs in its own subprocess (spawned, with a throwaway SQLite
database), so an analyzer crash, recursion blow-up or regex hang on one
model is recorded and the run continues.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from collections import Counter
from datetime import datetime
from multiprocessing.connection import wait
from pathlib import Path

from harness.discover import discover
from harness.report import render
from harness.worker import child_main

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "real_models"
DEFAULT_OUT = REPO_ROOT / "harness_reports"


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="python -m harness",
        description="Run real Power BI semantic models through the analyzer and measure its accuracy "
                    "against an independent parse of the same files.",
    )
    p.add_argument("corpus", nargs="?", default=str(DEFAULT_CORPUS),
                   help=f"directory of models (searched recursively; default: {DEFAULT_CORPUS})")
    p.add_argument("--out", help=f"output directory (default: {DEFAULT_OUT}/<timestamp>)")
    p.add_argument("--redact", action="store_true",
                   help="replace model/table/measure names with salted hashes and omit DAX, "
                        "so the report can be shared")
    p.add_argument("--timeout", type=float, default=180, help="seconds per model (default: 180)")
    p.add_argument("--jobs", type=int, default=max(1, min(4, (mp.cpu_count() or 2) // 2)),
                   help="models analyzed in parallel")
    p.add_argument("--limit", type=int, help="only analyze the first N models found")
    p.add_argument("--match", help="only analyze inputs whose path contains this text")
    return p.parse_args(argv)


def _run_all(root: Path, items, jobs: int, timeout: float, log) -> list[dict]:
    ctx = mp.get_context("spawn")
    pending = list(enumerate(items))
    running: dict = {}  # conn -> (index, item, proc, started)
    results: list[dict | None] = [None] * len(items)
    done = 0

    def finish(idx, item, result, started):
        nonlocal done
        done += 1
        results[idx] = result
        sev = Counter(f["severity"] for f in result.get("findings", []))
        log(f"[{done}/{len(items)}] {item.path}  {result['status']}  {time.monotonic() - started:.1f}s  "
            f"critical/high={sev['critical'] + sev['high']} medium={sev['medium']}")

    while pending or running:
        while pending and len(running) < jobs:
            idx, item = pending.pop(0)
            recv, send = ctx.Pipe(duplex=False)
            proc = ctx.Process(target=child_main, args=(str(root), item, send), daemon=True)
            proc.start()
            send.close()
            running[recv] = (idx, item, proc, time.monotonic())

        for conn in wait(list(running), timeout=0.5):
            idx, item, proc, started = running.pop(conn)
            try:
                result = conn.recv()
            except EOFError:
                code = proc.exitcode if proc.join(5) is None else proc.exitcode
                result = {"input": {"path": item.path, "kind": item.kind, "notes": item.notes},
                          "status": "crashed",
                          "error": {"type": "ProcessDied", "message": f"worker exited with code {code}",
                                    "traceback": ""},
                          "findings": [{"check": "process_died", "severity": "critical", "object": item.path,
                                        "detail": "the analyzer killed its process (segfault / out of memory)",
                                        "evidence": ""}]}
            proc.join(5)
            finish(idx, item, result, started)

        now = time.monotonic()
        for conn, (idx, item, proc, started) in list(running.items()):
            if now - started > timeout:
                proc.kill()
                proc.join(5)
                running.pop(conn)
                finish(idx, item, {
                    "input": {"path": item.path, "kind": item.kind, "notes": item.notes},
                    "status": "timeout",
                    "findings": [{"check": "timeout", "severity": "critical", "object": item.path,
                                  "detail": "analysis exceeded the per-model timeout (possible "
                                            "catastrophic regex backtracking or a very large model)",
                                  "evidence": f"timeout {timeout:.0f}s"}],
                }, started)
    return results


def main(argv=None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.corpus).resolve()
    if not root.is_dir():
        print(f"Corpus directory not found: {root}\n"
              f"Put models there (PBIP folders, .bim, .pbit, .json, .tmdl) or pass a path.", file=sys.stderr)
        return 2

    items = discover(root)
    if args.match:
        items = [i for i in items if args.match in i.path]
    skipped = [{"path": i.path, "reason": i.skip_reason} for i in items if i.skip_reason]
    items = [i for i in items if not i.skip_reason]
    if args.limit:
        items = items[: args.limit]
    if not items:
        print(f"No analyzable models found under {root}.", file=sys.stderr)
        for s in skipped:
            print(f"  skipped {s['path']}: {s['reason']}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else DEFAULT_OUT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    print(f"Analyzing {len(items)} input(s) from {root} with {args.jobs} worker(s); "
          f"{len(skipped)} skipped.", flush=True)

    t0 = time.monotonic()
    results = _run_all(root, items, args.jobs, args.timeout, lambda s: print(s, flush=True))
    summary = (f"{len(items)} input(s) from `{root.name}/` · {time.monotonic() - t0:.0f}s · "
               f"timeout {args.timeout:.0f}s")
    markdown, shareable = render(results, skipped, summary, args.redact)

    (out / "report.md").write_text(markdown)
    (out / "results.json").write_text(json.dumps({"results": shareable, "skipped": skipped},
                                                 indent=2, default=str))
    print(f"\nReport:  {out / 'report.md'}\nResults: {out / 'results.json'}")
    return 0
