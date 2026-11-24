"""Profile accepted Python and AgentLang programs from the mined-patterns experiment."""
import argparse
from datetime import datetime, timezone
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
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from agentlang import compile_python, compile_source
from benchmarks.long.runtime import run as runtime
from benchmarks.patterns.evaluation.cases import TASKS, TRACE_NAME, prepare, record, totals


def prepare_fixtures(task, directory):
    fixtures, manifests = {}, {}
    for variant in ("audit", "profile"):
        source = directory / task / variant / "input"
        source.mkdir(parents=True)
        case = prepare(task, variant, source)
        stdin = source.parent / "stdin"
        stdin.write_bytes(case["stdin"])
        fixtures[variant] = source, stdin, case["expected"]
        manifests[variant] = runtime.fixture_manifest(source, case["stdin"], case["expected"])
    if task == TRACE_NAME:
        # Predeclared after the main fixtures froze, before looking at any generated source.
        # This targeted diagnostic is kept out of grading, selection and timed samples.
        probe_dir = directory / task / "literal-diagnostic"
        probe_dir.mkdir()
        (probe_dir / "events.jsonl").write_bytes((HERE / "strict-json.jsonl").read_bytes())
        expected = {"runs": [record("real", "ok", input_tokens=3, output_tokens=7)],
                    "totals": totals(1, 0, 0, 0, 3, 7)}
        fixtures["literal-diagnostic"] = probe_dir, fixtures["audit"][1], expected
        manifests["literal-diagnostic"] = runtime.fixture_manifest(probe_dir, b"", expected)
    return fixtures, manifests


def profile_pair(task, model_round, pair, fixtures, directory, observations, args, env, rng):
    entry = {"task": task, "round": model_round, "candidates": pair}
    if not all(pair.get(arm) for arm in ("python", "compact")):
        # The supplemental probe still covers any accepted, unmatched held-out candidate.
        if task == TRACE_NAME:
            outcomes = {}
            for arm, build in (("python", compile_python), ("compact", compile_source)):
                if pair.get(arm):
                    path = runtime.source_path(pair[arm]["path"], observations)
                    script = directory / f"unmatched-{model_round}-{arm}.py"
                    script.write_text(build(path.read_text(encoding="utf-8")), encoding="utf-8")
                    try:
                        runtime.isolated_measure([sys.executable, str(script)], fixtures["literal-diagnostic"],
                                                 directory, env, args.timeout)
                        outcomes[arm] = "pass"
                    except (ValueError, TimeoutError) as error:
                        outcomes[arm] = str(error)
            entry["supplemental_strict_json"] = outcomes
        entry["status"] = "unmatched"
        return entry
    # Use each arm's actual launcher; the Python arm receives the same public helper callables.
    compiled = directory / task / f"round-{model_round}"
    compiled.mkdir()
    commands = runtime.commands_for(pair, compiled, observations)
    python_source = runtime.source_path(pair["python"]["path"], observations)
    commands["python_fresh"] = [sys.executable, str(HERE / "native.py"), str(python_source)]
    entry["audit"] = runtime.audit_pair(commands, fixtures["audit"], directory, env, args.timeout)
    if "literal-diagnostic" in fixtures:
        entry["supplemental_strict_json"] = runtime.audit_pair(
            commands, fixtures["literal-diagnostic"], directory, env, args.timeout,
        )
    if set(entry["audit"].values()) != {"pass"}:
        entry["status"] = "failed_audit"
        return entry
    measured = runtime.bench_case(commands, fixtures["profile"], directory, env, args, rng)
    entry.update(status=measured["status"], profile=measured)
    return entry


def program_medians(pairs):
    output = {}
    for task in TASKS:
        ok = [p for p in pairs if p["task"] == task and p["status"] == "passed"]
        output[task] = {"matched_rounds": [p["round"] for p in ok]}
        if ok:
            output[task]["modes"] = {
                mode: {key: round(statistics.median(p["profile"]["summary"][mode][key][2] for p in ok), 4)
                       for key in runtime.TIMES}
                for mode in runtime.MODES
            }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=HERE.parent / "generation/observations/results.json")
    parser.add_argument("--output", type=Path, default=HERE / "runtime.json")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.runs < 1 or args.timeout <= 0 or sys.platform not in {"darwin", "linux"}:
        parser.error("requires macOS or Linux, positive --runs and --timeout")
    signal.signal(signal.SIGALRM, runtime.timed_out)
    start = time.monotonic()
    raw = args.trials.read_bytes()
    generation = json.loads(raw)
    observations = args.trials.resolve().parent
    grouped = runtime.candidates(generation["trials"], observations)
    counts = generation["rounds_by_task"]
    expected_keys = {(task, n) for task in TASKS for n in range(1, counts[task] + 1)}
    if grouped.keys() != expected_keys or any(r.keys() != {"python", "compact"} for r in grouped.values()):
        parser.error("wait for every scheduled trial before profiling")
    hashes = runtime.file_hashes()
    for script in (HERE / "cases.py", HERE / "native.py", HERE / "profile.py", HERE / "strict-json.jsonl"):
        hashes[str(script.relative_to(ROOT))] = runtime.sha256(script.read_bytes())
    cpu = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        probe = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
        cpu = probe.stdout.strip() or cpu
    report = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"cpu": cpu, "platform": platform.platform(), "python": platform.python_version(),
                        "logical_cpus": os.cpu_count()},
        "config": {"runs": args.runs, "warmups": 1, "seed": args.seed, "variants": ["profile"],
                   "timeout_s": args.timeout, "PYTHONHASHSEED": 0},
        "input_sha256": runtime.sha256(raw), "implementation_sha256": hashes,
        "sample_columns": runtime.COLUMNS, "summary_columns": ["min", "p25", "median", "p75", "max"],
        "fixtures": {}, "pairs": [],
    }
    rng = random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix="agentlang-patterns-") as directory:
        temp = Path(directory)
        env = {"PATH": os.defpath, "HOME": directory, "PYTHONPATH": str(ROOT),
               "PYTHONHASHSEED": "0", "LC_ALL": "C", "PYTHONUTF8": "1"}
        for task in TASKS:
            fixtures, report["fixtures"][task] = prepare_fixtures(task, temp)
            for n in range(1, counts[task] + 1):
                entry = profile_pair(task, n, grouped[task, n], fixtures, temp, observations, args, env, rng)
                report["pairs"].append(entry)
                print(f"{task} round {n}: {entry['status']}", flush=True)
    report["median_of_program_medians"] = program_medians(report["pairs"])
    report["harness_elapsed_s"] = round(time.monotonic() - start, 4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
