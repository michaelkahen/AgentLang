"""Measure normal run dispatch, full argument parsing and precompiled tiny scripts."""

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
from benchmarks.scripting.launches import ROOT, stage_package


def run():
    rng = random.Random(982)
    rounds = 12
    orders = [{"cents": 300, "paid": True}, {"cents": 900, "paid": False},
              {"cents": 50, "paid": True}]
    people = [{"name": "a", "score": 3}, {"name": "b", "score": 7}]
    fixtures = [
        ("paid_total", orders, 350),
        ("order_summary", orders, {"total": 350, "orders": 3}),
        ("leaders", people, {"names": ["b", "a"], "leaders": people[::-1]}),
    ]
    signal.signal(signal.SIGALRM, timed_out)
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        cwd = Path(temp)
        hashes = stage_package(cwd)
        env = {"PATH": os.defpath, "PYTHONPATH": str(cwd), "PYTHONUTF8": "1", "PYTHONHASHSEED": "0"}
        for name, value, expected in fixtures:
            filename = ROOT / "examples" / "terse" / (name + ".ag")
            stdin = cwd / "stdin.json"
            stdin.write_text(json.dumps(value))
            emitted = cwd / "script.py"
            subprocess.run([sys.executable, "-m", "agentlang", "compile", str(filename), "-o", str(emitted)],
                           cwd=cwd, env=env, check=True)
            for startup, flags in (("normal", []), ("without_site", ["-S"])):
                py = [sys.executable, *flags]
                cli = [*py, "-m", "agentlang", "run"]
                commands = {"direct": [*cli, str(filename)], "argparse": [*cli, "--", str(filename)],
                            "precompiled": [*py, str(emitted)]}
                samples = {k: [] for k in commands}
                for i in range(rounds + 1):
                    if i <= 1 or (i - 1) % len(commands) == 0:
                        order = list(commands)
                        rng.shuffle(order)
                    else:
                        order = order[1:] + order[:1]
                    for key in order:
                        wall, _, _, cpu, *_ = measure(commands[key], cwd, env, stdin, expected, 30)
                        if i:
                            samples[key].append([wall, cpu])
                rows.append({"example": name, "startup": startup, "samples": samples,
                             "median_ms": {k: list(map(statistics.median, zip(*v))) for k, v in samples.items()}})
    return {"package_sha256": hashes, "python": platform.python_version(), "platform": platform.platform(),
            "seed": 982, "warmups": 1, "rounds": rounds, "columns": ["wall_ms", "cpu_ms"], "cases": rows}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
