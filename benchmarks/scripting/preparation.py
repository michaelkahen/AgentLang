"""Time full in-memory script preparation with three statement-scanning strategies."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import statistics
import time
from unittest.mock import patch

from agentlang import compiler

ROOT = Path(__file__).resolve().parents[2]
SEED = 22791


def sources():
    paths = sorted((ROOT / "benchmarks").glob("**/generation/**/sources/*.ag"))
    paths += sorted((ROOT / "examples").rglob("*.ag"))
    seen = set()
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if source not in seen:
            seen.add(source)
            yield str(path.relative_to(ROOT)), source


def run(rounds):
    # All three arms use the same release, parser, helper bindings and Python
    # compiler. Change only which sources get sent to the statement tokenizer.
    commands = "|".join(compiler._COMMANDS)
    stages = "|".join(sorted(compiler._STAGES | compiler._SHORT_STAGES.keys()))
    patterns = {
        "always": re.compile(""),
        "any_command_name": re.compile(
            rf"\b(?:{commands})\b|[:|][ \t\f]*(?:{stages})\b|\\\r?\n"
        ),
        "command_at_statement_start": compiler._STATEMENT_MARKERS,
    }
    rng = random.Random(SEED)
    rows = []
    for filename, source in sources():
        expanded = compiler._expand_fields(source, filename)
        samples = {name: [] for name in patterns}
        cpu_samples = {name: [] for name in patterns}
        with patch.object(compiler, "_STATEMENT_MARKERS", patterns["always"]):
            reference = compiler.compile_source(source, filename)
        for name, regex in patterns.items():
            with patch.object(compiler, "_STATEMENT_MARKERS", regex):
                if compiler.compile_source(source, filename) != reference:
                    raise AssertionError((filename, name))
        for index in range(rounds + 2):
            order = list(patterns)
            rng.shuffle(order)
            for name in order:
                with patch.object(compiler, "_STATEMENT_MARKERS", patterns[name]):
                    start = time.perf_counter_ns()
                    cpu_start = time.process_time_ns()
                    artifact = compiler.prepare_run(source, filename)
                    cpu_ns = time.process_time_ns() - cpu_start
                    elapsed = time.perf_counter_ns() - start
                    del artifact
                if index >= 2:
                    samples[name].append(elapsed)
                    cpu_samples[name].append(cpu_ns)
        rows.append({
            "source": filename,
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "scanned": {k: bool(v.search(expanded)) for k, v in patterns.items()},
            "median_wall_us": {k: round(statistics.median(v) / 1000, 3) for k, v in samples.items()},
            "median_cpu_us": {k: round(statistics.median(v) / 1000, 3) for k, v in cpu_samples.items()},
        })
    totals = {metric: {k: round(sum(r[metric][k] for r in rows), 3) for k in patterns}
              for metric in ("median_wall_us", "median_cpu_us")}
    return {
        "python": platform.python_version(), "platform": platform.platform(), "seed": SEED,
        "measured_rounds_per_script": rounds, "warmup_rounds": 2, "unit": "microseconds",
        "sum_of_script_medians_us": totals, "sources": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=60)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    print(json.dumps(run(args.rounds), indent=2))
