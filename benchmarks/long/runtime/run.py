"""Measure paired, verified generated programs on macOS or Linux."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from agentlang import compile_python, compile_source
from benchmarks.long.workloads.cases import TASKS, matches, prepare

MODES = ("python_fresh", "compact_fresh", "python_prepared", "compact_prepared")
COLUMNS = ("round", "position", "wall_ms", "user_ms", "system_ms", "cpu_ms",
           "peak_rss_mib", "stdout_bytes", "stderr_bytes", "minor_faults", "major_faults",
           "block_inputs", "block_outputs", "new_or_changed_files", "new_or_changed_file_bytes")
TIMES = ("wall_ms", "cpu_ms", "user_ms", "system_ms", "peak_rss_mib")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def timed_out(signum, frame):
    raise TimeoutError("candidate exceeded the per-process timeout")


def measure(command, cwd, env, input_file, expected, timeout):
    """Use wait4 on this PID so CPU and memory measurements refer to one process."""
    with input_file.open("rb") as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        started = time.perf_counter_ns()
        with subprocess.Popen(command, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr) as child:
            signal.setitimer(signal.ITIMER_REAL, timeout)
            try:
                _, status, usage = os.wait4(child.pid, 0)
                elapsed = time.perf_counter_ns() - started
                child.returncode = os.waitstatus_to_exitcode(status)
            except TimeoutError:
                child.kill()
                child.wait()
                raise
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        if child.returncode:
            stderr.seek(0)
            message = stderr.read(300).decode("utf-8", errors="replace")
            raise ValueError(f"exit {child.returncode}: {message}")
        stdout.seek(0)
        output = stdout.read()
        if not matches(output, expected):
            raise ValueError("stdout JSON differs from the independent oracle")
        usage_ms = [round(usage.ru_utime * 1000, 4), round(usage.ru_stime * 1000, 4)]
        rss_mib = usage.ru_maxrss / (1024**2 if sys.platform == "darwin" else 1024)
        return [
            round(elapsed / 1_000_000, 4), *usage_ms, round(sum(usage_ms), 4), round(rss_mib, 4),
            len(output), os.fstat(stderr.fileno()).st_size, usage.ru_minflt, usage.ru_majflt,
            usage.ru_inblock, usage.ru_oublock,
        ]


def rounds(number, rng):
    modes = list(MODES)
    for index in range(number):
        offset = index % len(modes)
        if offset == 0:
            rng.shuffle(modes)
        yield modes[offset:] + modes[:offset]


def summarize(rows):
    summary = {}
    for key in TIMES:
        values = [r[COLUMNS.index(key)] for r in rows]
        quartiles = statistics.quantiles(values, method="inclusive") if len(values) > 1 else values * 3
        summary[key] = [round(v, 4) for v in [min(values), *quartiles, max(values)]]
    return summary


def source_path(name, observations):
    path = Path(name)
    # The collector records project-relative names inside the repo and local names elsewhere.
    if path.parts[0] == "sources":
        return observations / path
    return ROOT / path


def paired_summaries(pairs, variants):
    """Give each generated program equal weight, independent of the repeat count."""
    tables = {}
    for task in TASKS:
        matched = [p for p in pairs if p["task"] == task and p["status"] == "passed"]
        tables[task] = {"matched_rounds": [p["round"] for p in matched], "variants": {}}
        if not matched:
            continue
        for variant in variants:
            summaries = [p["variants"][variant]["summary"] for p in matched]
            tables[task]["variants"][variant] = {
                mode: {
                    key: round(statistics.median(s[mode][key][2] for s in summaries), 4)
                    for key in TIMES
                }
                for mode in MODES
            }
    return tables


def candidates(trials, observations):
    grouped = {}
    for trial in trials:
        key = (trial["task"], trial["round"])
        row = grouped.setdefault(key, {})
        arm = trial["arm"]
        if arm in row:
            raise ValueError(f"duplicate trial for {key} / {arm}")
        row[arm] = None
        if trial["passed"]:
            for index, attempt in enumerate(trial["attempts"], 1):
                if attempt["passed"]:
                    name = attempt["source_path"]
                    path = source_path(name, observations)
                    row[arm] = {
                        "attempt": index, "path": name,
                        "source_bytes": path.stat().st_size, "sha256": sha256(path.read_bytes()),
                    }
                    break
            if row[arm] is None:
                raise ValueError(f"passing trial {key} / {arm} lacks a passing attempt")
    return grouped


def commands_for(pair, compiled, observations):
    commands = {}
    for arm, build in (("python", compile_python), ("compact", compile_source)):
        path = source_path(pair[arm]["path"], observations)
        text = build(path.read_text(encoding="utf-8"), str(path))
        emitted = compiled / f"{arm}.py"
        emitted.write_text(text, encoding="utf-8")
        pair[arm]["emitted_bytes"] = emitted.stat().st_size
        pair[arm]["emitted_sha256"] = sha256(emitted.read_bytes())
        pair[arm]["emitted_equals_source"] = pair[arm]["emitted_sha256"] == pair[arm]["sha256"]
        commands[arm + "_prepared"] = [sys.executable, str(emitted)]
        if arm == "python":
            commands["python_fresh"] = [sys.executable, str(HERE / "native.py"), str(path)]
        else:
            commands["compact_fresh"] = [sys.executable, "-m", "agentlang", "run", str(path)]
    return commands


def fixture_manifest(directory, stdin, expected):
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(directory))] = {"bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())}
    return {
        "files": files, "input_file_bytes": sum(row["bytes"] for row in files.values()),
        "stdin_bytes": len(stdin), "stdin_sha256": sha256(stdin),
        "expected_json_sha256": sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()),
    }


def isolated_measure(command, fixture, temp, env, timeout):
    template, stdin, expected = fixture
    # File copying and oracle verification are outside the timer.
    with tempfile.TemporaryDirectory(dir=temp) as fresh:
        cwd = Path(fresh)
        shutil.copytree(template, cwd, dirs_exist_ok=True)

        def file_state():
            state = {}
            for path in cwd.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    stat = path.stat()
                    state[path] = (stat.st_size, stat.st_mtime_ns)
            return state

        before = file_state()
        row = measure(command, cwd, env, stdin, expected, timeout)
        changed = [size for path, (size, mtime) in file_state().items()
                   if before.get(path) != (size, mtime)]
        return [*row, len(changed), sum(changed)]


def audit_pair(commands, fixture, temp, env, timeout):
    verdicts = {}
    for arm in ("python", "compact"):
        try:
            isolated_measure(commands[arm + "_prepared"], fixture, temp, env, timeout)
            verdicts[arm] = "pass"
        except (ValueError, TimeoutError) as err:
            verdicts[arm] = str(err)
    return verdicts


def bench_case(commands, fixture, temp, env, args, rng):
    samples = {mode: [] for mode in MODES}
    for round_num, order in enumerate([*rounds(1, rng), *rounds(args.runs, rng)]):
        for position, mode in enumerate(order, 1):
            try:
                row = isolated_measure(commands[mode], fixture, temp, env, args.timeout)
            except (ValueError, TimeoutError) as err:
                return {"status": "failed", "mode": mode, "round": round_num, "error": str(err)}
            if round_num:
                samples[mode].append([round_num, position, *row])
    return {
        "status": "passed", "samples": samples,
        "summary": {mode: summarize(rows) for mode, rows in samples.items()},
    }


def file_hashes():
    paths = [HERE / "run.py", HERE / "native.py", HERE.parent / "workloads" / "cases.py"]
    paths.extend(sorted((ROOT / "agentlang").glob("*.py")))
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=HERE.parent / "generation" / "observations" / "results.json")
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    parser.add_argument("--runs", type=int, default=8, help="Recorded runs per program, mode, and fixture size.")
    parser.add_argument("--variants", nargs="+", choices=["base", "profile"], default=["base", "profile"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.runs < 1 or args.timeout <= 0 or sys.platform not in {"darwin", "linux"}:
        parser.error("requires macOS or Linux, positive --runs and --timeout")
    signal.signal(signal.SIGALRM, timed_out)
    started = time.monotonic()
    trials_bytes = args.trials.read_bytes()
    generation = json.loads(trials_bytes)
    observations = args.trials.resolve().parent
    grouped = candidates(generation["trials"], observations)
    expected_trials = len(TASKS) * len(("python", "compact")) * generation["rounds"]
    if sum(len(row) for row in grouped.values()) != expected_trials:
        parser.error("the model-generation run is incomplete; wait for all trials before profiling")
    rng = random.Random(args.seed)
    # Keep the local project importable. Record only relevant, non-identifying environment details.
    env = {"PATH": os.defpath, "LC_ALL": "C", "PYTHONHASHSEED": "0",
           "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    cpu = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        model = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
        cpu = model.stdout.strip() or cpu
    result = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"platform": platform.platform(), "cpu": cpu, "logical_cpus": os.cpu_count(),
                        "python": platform.python_version()},
        "config": {"runs": args.runs, "warmups": 1, "seed": args.seed, "variants": args.variants,
                   "timeout_s": args.timeout, "PYTHONHASHSEED": 0},
        "input_sha256": sha256(trials_bytes), "implementation_sha256": file_hashes(),
        "sample_columns": COLUMNS, "summary_columns": ["min", "p25", "median", "p75", "max"],
        "fixtures": {}, "pairs": [],
    }
    with tempfile.TemporaryDirectory(prefix="agentlang-long-") as tmp:
        temp = Path(tmp)
        env["HOME"] = tmp
        for task in TASKS:
            keys = sorted(k for k in grouped if k[0] == task)
            if not keys:
                continue
            fixtures = {}
            result["fixtures"][task] = {}
            for variant in ["audit", *dict.fromkeys(args.variants)]:
                template = temp / task / variant / "fixtures"
                template.mkdir(parents=True)
                prepared = prepare(task, variant, template)
                stdin = template.parent / "stdin"
                stdin.write_bytes(prepared["stdin"])
                fixtures[variant] = (template, stdin, prepared["expected"])
                result["fixtures"][task][variant] = fixture_manifest(template, prepared["stdin"], prepared["expected"])
            for _, model_round in keys:
                pair = grouped[task, model_round]
                entry = {"task": task, "round": model_round, "candidates": pair}
                result["pairs"].append(entry)
                if not all(pair.get(arm) for arm in ("python", "compact")):
                    entry["status"] = "unmatched"
                    continue
                compiled = temp / task / f"round-{model_round}"
                compiled.mkdir()
                commands = commands_for(pair, compiled, observations)
                entry["audit"] = audit_pair(commands, fixtures["audit"], temp, env, args.timeout)
                if any(verdict != "pass" for verdict in entry["audit"].values()):
                    entry["status"] = "failed_audit"
                    print(f"{task} round {model_round}: excluded by audit", flush=True)
                    continue
                entry["variants"] = {}
                for variant in args.variants:
                    measured = bench_case(commands, fixtures[variant], temp, env, args, rng)
                    entry["variants"][variant] = measured
                    print(f"{task} round {model_round} {variant}: {measured['status']}", flush=True)
                entry["status"] = "passed" if all(v["status"] == "passed" for v in entry["variants"].values()) else "failed"
    result["median_of_program_medians"] = paired_summaries(result["pairs"], args.variants)
    result["harness_elapsed_s"] = round(time.monotonic() - started, 4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
