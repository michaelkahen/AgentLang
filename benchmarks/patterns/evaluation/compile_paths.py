"""Compare two compilation paths on the same six archived, audited AgentLang sources."""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from agentlang.compiler import compile_source, prepare_run
from benchmarks.long.workloads.cases import matches, prepare


def emit_then_compile(text, filename):
    return compile(compile_source(text, filename), filename, "exec")


def verify(source, text, task):
    with tempfile.TemporaryDirectory() as directory:
        cwd = Path(directory)
        fixture = prepare(task, "audit", cwd)
        emitted = cwd / "candidate.py"
        emitted.write_text(compile_source(text, str(source)), encoding="utf-8")
        for cmd in ([sys.executable, str(emitted)], [sys.executable, "-m", "agentlang", "run", str(source)]):
            out = subprocess.run(cmd, cwd=cwd, input=fixture["stdin"], capture_output=True, check=True,
                                 env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}, timeout=10)
            if not matches(out.stdout, fixture["expected"]):
                raise ValueError(f"{source.name} failed the archived audit with {cmd[1]}")


def main():
    old = ROOT / "benchmarks/long/generation/required/results.json"
    trials = json.loads(old.read_bytes())["trials"]
    sources = [(r["task"], ROOT / next(a["source_path"] for a in r["attempts"] if a["passed"]))
               for r in trials if r["passed"] and r["arm"] == "compact"]
    report = {
        "python": platform.python_version(), "platform": platform.platform(), "runs": 20, "warmups": 2,
        "manifest_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
        "compiler_sha256": hashlib.sha256((ROOT / "agentlang/compiler.py").read_bytes()).hexdigest(),
        "sources": [],
    }
    funcs = (("emitted", emit_then_compile), ("direct", prepare_run))
    for task, source in sources:
        text = source.read_text(encoding="utf-8")
        filename = str(source.relative_to(ROOT))
        verify(source, text, task)
        row = {"path": filename, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "audit": "pass",
               "wall_us": {"emitted": [], "direct": []}}
        for n in range(report["warmups"] + report["runs"]):
            for key, function in (funcs if n % 2 == 0 else reversed(funcs)):
                started = time.perf_counter_ns()
                artifact = function(text, filename)
                elapsed = (time.perf_counter_ns() - started) / 1000
                del artifact
                if n >= report["warmups"]:
                    row["wall_us"][key].append(round(elapsed, 3))
        row["median_us"] = {key: statistics.median(values) for key, values in row["wall_us"].items()}
        report["sources"].append(row)
    report["median_of_source_medians_us"] = {
        key: statistics.median(row["median_us"][key] for row in report["sources"]) for key, _ in funcs
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "compile-paths.json"
    out.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(report["median_of_source_medians_us"])


if __name__ == "__main__":
    main()
