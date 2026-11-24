"""Recheck accepted programs on three original fixtures and an unseen audit fixture."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from agentlang import compile_python, compile_source
from benchmarks.long.workloads.cases import matches, prepare

VARIANTS = ("base", "edges", "profile", "audit")


def replay(row, records):
    attempt = next((item for item in row["attempts"] if item["passed"]), None)
    result = {"task": row["task"], "round": row["round"], "arm": row["arm"]}
    if attempt is None:
        return {**result, "status": "no accepted program"}
    source = Path(attempt["source_path"])
    path = ROOT / source if source.parts[0] == "benchmarks" else records.parent / source
    build = compile_python if row["arm"] == "python" else compile_source
    result.update(attempt=attempt["attempt"], source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    checks = {}
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        try:
            program = directory / "program.py"
            program.write_text(build(path.read_text(encoding="utf-8"), path.name), encoding="utf-8")
        except SyntaxError:
            return {**result, "status": "compile error"}
        for name in VARIANTS:
            work = directory / name
            fixture = prepare(row["task"], name, work)
            try:
                proc = subprocess.run([sys.executable, "-I", "-B", program], cwd=work,
                                      input=fixture["stdin"], capture_output=True, timeout=15)
                if proc.returncode:
                    status = "execution failed"
                else:
                    status = "pass" if matches(proc.stdout, fixture["expected"]) else "output mismatch"
            except subprocess.TimeoutExpired:
                status = "timeout"
            checks[name] = status
    return {**result, "checks": checks, "status": "pass" if all(v == "pass" for v in checks.values()) else "failed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=HERE / "generation/observations/results.json")
    parser.add_argument("--output", type=Path, help="optionally save the replay manifest")
    args = parser.parse_args()
    records = args.trials.read_bytes()
    rows = [replay(row, args.trials.resolve()) for row in json.loads(records)["trials"]]
    for row in rows:
        print(f"{row['task']:15s} {row['arm']:8s} round {row['round']}  {row['status']}")
    if args.output:
        report = {"variants": list(VARIANTS), "trial_manifest_sha256": hashlib.sha256(records).hexdigest(),
                  "results": rows}
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return int(any(row["status"] != "pass" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
