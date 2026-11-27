"""Replay the 16 archived scripts using the previous and updated public CLI."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import signal
import statistics
import subprocess
import sys
import tempfile

from benchmarks.long.runtime.run import measure, timed_out
from benchmarks.patterns.evaluation.cases import TASKS, prepare

ROOT = Path(__file__).resolve().parents[2]
BASE = "8a5b5c538912000a18eedb100cb4402da5960d7c"
ARCHIVE = ROOT / "benchmarks/patterns/generation/observations/sources"


def stage_package(directory, revision=None):
    """Stage both packages on the same filesystem with fresh bytecode caches."""
    package = directory / "agentlang"
    package.mkdir(parents=True)
    hashes = {}
    for name in ("__init__.py", "__main__.py", "compiler.py", "helpers.py"):
        path = Path("agentlang") / name
        data = (subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=ROOT)
                if revision else (ROOT / path).read_bytes())
        (package / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    return hashes


def run(rounds):
    rng = random.Random(55981)
    rows = []
    signal.signal(signal.SIGALRM, timed_out)
    with tempfile.TemporaryDirectory() as tempdir:
        temp = Path(tempdir)
        packages = {k: stage_package(temp / k, rev)
                    for k, rev in (("before", BASE), ("after", None))}
        envs = {k: {"PATH": os.defpath, "PYTHONPATH": str(temp / k),
                    "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"} for k in packages}
        jobs = [(p, task, variant) for task in TASKS
                for p in sorted(ARCHIVE.glob(f"{task}-compact-*.ag"))
                for variant in ("audit", "profile")]
        rng.shuffle(jobs)
        for source, task, variant in jobs:
            cwd = temp / "fixtures" / task / variant
            fixture = prepare(task, variant, cwd)
            stdin = cwd / "stdin.bin"
            stdin.write_bytes(fixture["stdin"])
            cmd = [sys.executable, "-m", "agentlang", "run", str(source)]
            samples = {k: [] for k in packages}
            for i in range(rounds + 1):
                if i % 2 or i == 0:
                    order = list(packages)
                    rng.shuffle(order)
                else:
                    order.reverse()
                for name in order:
                    wall, _, _, cpu, *_ = measure(cmd, cwd, envs[name], stdin, fixture["expected"], 30)
                    if i:
                        samples[name].append([wall, cpu])
            rows.append({"source": str(source.relative_to(ROOT)),
                         "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "task": task,
                         "fixture": variant, "samples": samples})
    ratios = {}
    for variant in ("audit", "profile"):
        ratios[variant] = {}
        for col, metric in enumerate(("wall", "cpu")):
            paired = []
            for row in rows:
                if row["fixture"] == variant:
                    arms = row["samples"]
                    after = statistics.median(sample[col] for sample in arms["after"])
                    before = statistics.median(sample[col] for sample in arms["before"])
                    paired.append(after / before)
            ratios[variant][metric] = round(statistics.median(paired), 5)
    return {"python": platform.python_version(), "platform": platform.platform(),
            "baseline": BASE, "package_sha256": packages, "seed": 55981,
            "measured_rounds": rounds, "warmups": 1, "sample_columns": ["wall_ms", "cpu_ms"],
            "median_of_paired_ratios": ratios, "pairs": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    print(json.dumps(run(args.rounds), indent=2))
