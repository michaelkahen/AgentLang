"""Measure adopting the two record spellings on the programs they shorten."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import platform
import random
from statistics import median
from time import perf_counter_ns, process_time_ns

from agentlang import compile_source
from agentlang.compiler import prepare_run
from benchmarks.scripting.simulation_archive import BASELINE, apply, eligible_edits, sources, tooling_sources


ROOT = Path(__file__).resolve().parents[2]
SEED = 842097


def changed_programs(programs):
    seen = set()
    for filename, source, _ in programs:
        if source in seen:
            continue
        seen.add(source)
        gets, records = eligible_edits(source)
        if gets or records:
            edits = gets + [edit for record in records for edit in record]
            yield filename, source, apply(source, edits)


def measure(filename, authored, combined, rounds, rng):
    arms = {"authored": authored, "combined": combined}
    trees = [ast.dump(ast.parse(compile_source(s, filename))) for s in arms.values()]
    if trees[0] != trees[1]:
        raise ValueError(f"{filename}: combined spelling changed the AST")
    samples = {metric: {k: [] for k in arms} for metric in ("cpu", "wall")}
    for i in range(rounds + 2):
        order = list(arms)
        rng.shuffle(order)
        for k in order:
            start = perf_counter_ns()
            cpu_start = process_time_ns()
            artifact = prepare_run(arms[k], filename)
            cpu = process_time_ns() - cpu_start
            wall = perf_counter_ns() - start
            del artifact
            if i >= 2:
                samples["cpu"][k].append(cpu)
                samples["wall"][k].append(wall)
    return {
        "path": filename,
        "sha256": {k: hashlib.sha256(s.encode()).hexdigest() for k, s in arms.items()},
        "median_us": {metric: {k: median(values) / 1000 for k, values in timings.items()}
                      for metric, timings in samples.items()},
    }


def run(rounds):
    rng = random.Random(SEED)
    result = {}
    for group, original in (("archive", sources(ROOT)), ("tooling", tooling_sources(ROOT))):
        cases = list(changed_programs(original))
        rng.shuffle(cases)
        programs = [measure(*case, rounds, rng) for case in cases]
        summary = {}
        for metric in ("cpu", "wall"):
            pairs = [p["median_us"][metric] for p in programs]
            totals = {k: round(sum(p[k] for p in pairs), 3) for k in ("authored", "combined")}
            ratios = [p["combined"] / p["authored"] for p in pairs]
            summary[metric] = {
                "sum_of_program_medians_us": totals,
                "median_program_ratio": round(median(ratios), 6),
                "median_program_difference_us": round(median(p["combined"] - p["authored"] for p in pairs), 3),
                "slower_programs": sum(r > 1 for r in ratios),
            }
        result[group] = {"program_count": len(programs), "summary": summary, "programs": programs}
    return {"python": platform.python_version(), "platform": platform.platform(),
            "baseline_revision": BASELINE, "compiler_sha256": hashlib.sha256(
                (ROOT / "agentlang/compiler.py").read_bytes()).hexdigest(),
            "seed": SEED, "measured_pairs_per_program": rounds, "warmup_pairs": 2, **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=21)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    print(json.dumps(run(args.rounds), indent=2))
