"""Run the fixed paired trial schedule, grading each source before any repair."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from agentlang import compile_python, compile_source, count_short_stages
from benchmarks.long.generation.run import ENCODING, LIMITS, VARIANTS, monitored
from benchmarks.patterns.evaluation.cases import PROMPTS, TASKS, matches, prepare
from benchmarks.patterns.generation.client import HERE, MODEL, invoke
import tiktoken


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def prompt(task, arm, previous=None, diagnostic=None):
    language = "Python" if arm == "python" else "AgentLang"
    components = [f"Write concise {language}. Source only; no tools. Standard library allowed.",
                  (HERE / "operations.txt").read_text(encoding="utf-8").strip()]
    if arm == "compact":
        components.append((HERE / "syntax.txt").read_text(encoding="utf-8").strip())
    components.append(PROMPTS[task])
    if diagnostic:
        components.extend([f"Repair the previous program: {diagnostic}", previous or "(no program returned)"])
    return "\n\n".join(components)


def schedule():
    cases = []
    for r in range(4):
        for offset in range(len(TASKS)):
            i = (r + offset) % len(TASKS)
            arms = ("python", "compact") if (r + i) % 2 == 0 else ("compact", "python")
            cases.extend({"task": TASKS[i], "round": r + 1, "arm": arm} for arm in arms)
    return cases


def check_fixture(program, task, variant, deadline):
    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory)
        case = prepare(task, variant, fixture)
        (fixture / "candidate.py").write_text(program, encoding="utf-8")
        timeout = min(LIMITS["grading_seconds"], deadline - time.perf_counter())
        if timeout <= 0:
            return "validation exceeded the trial time budget"
        cmd = [sys.executable, "-I", "-B", "candidate.py"]
        if sys.platform == "darwin":
            policy = ("(version 1)(allow default)(deny network*)(deny file-write*)"
                      f"(allow file-write* (subpath {json.dumps(str(fixture.resolve()))}))")
            cmd = ["/usr/bin/sandbox-exec", "-p", policy, *cmd]
        out, err, usage = monitored(cmd, case["stdin"], fixture, timeout,
                                    env={"PATH": os.defpath, "LC_ALL": "C", "HOME": directory})
    if usage["timed_out"]:
        return "execution timed out"
    if usage["exit"]:
        last = err.decode(errors="replace").splitlines()[-1:] or [""]
        kind = last[0].split(":", 1)[0]
        return "execution raised " + kind if kind.isidentifier() else "execution failed"
    return "pass" if matches(out, case["expected"]) else "incorrect JSON output"


def grade(source, task, arm, variants, deadline):
    compiler = compile_python if arm == "python" else compile_source
    checks = {}
    try:
        program = compiler(source, "<candidate>")
        compile(program, "<candidate>", "exec")
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        location = f" on line {line}" if line else ""
        return "The program did not compile" + location + ".", checks
    for variant in variants:
        verdict = check_fixture(program, task, variant, deadline)
        checks[variant] = verdict
        if verdict != "pass":
            return f"Fixture {variant} failed ({verdict}).", checks
    return None, checks


def syntax_use(source):
    try:
        lowered = compile_source(source)
    except (SyntaxError, ValueError):
        return None, None
    try:
        native = compile_python(source)
    except (SyntaxError, ValueError):
        native = None
    return lowered != native, count_short_stages(source)


def save_source(out, entry, index, source, seen):
    if not source:
        return None
    fingerprint = digest(source)
    key = (entry["arm"], fingerprint)
    if key not in seen:
        ext = ".py" if entry["arm"] == "python" else ".ag"
        name = f"{entry['task']}-{entry['arm']}-r{entry['round']}-a{index}{ext}"
        path = out / "sources" / name
        path.write_text(source, encoding="utf-8")
        seen[key] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT / "benchmarks") else str(Path("sources") / name)
    return seen[key]


def run_trial(entry, profile, out, enc, seen):
    start = time.perf_counter()
    deadline = start + LIMITS["trial_seconds"]
    row = dict(entry, started_utc=now(), passed=False, attempts=[])
    previous = feedback = None
    for index in range(1, LIMITS["attempts"] + 1):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        request = prompt(entry["task"], entry["arm"], previous, feedback)
        source, metrics, problem = invoke(request, profile, min(remaining, LIMITS["attempt_seconds"]))
        begin_grade = time.perf_counter()
        verdicts = {}
        if problem is None:
            problem, verdicts = grade(source, entry["task"], entry["arm"], VARIANTS, deadline)
        elapsed_through_grade = time.perf_counter() - start
        grade_s = time.perf_counter() - begin_grade
        path = save_source(out, entry, index, source, seen)
        used, stages = syntax_use(source) if source and entry["arm"] == "compact" else (False, None)
        row["attempts"].append({
            "attempt": index, "passed": problem is None, "diagnostic": problem, "fixtures": verdicts,
            "source_path": path, "source_sha256": digest(source) if source else None,
            "request_sha256": digest(request), "prompt_tokens": len(enc.encode(request)),
            "visible_source_tokens": len(enc.encode(source)), "uses_shorthand": used,
            "short_stage_count": stages, "generation": metrics, "validation_s": round(grade_s, 5),
        })
        if problem is None:
            row["passed"] = True
            break
        previous, feedback = source, problem
    row["wall_s"] = round(elapsed_through_grade if row["passed"] else time.perf_counter() - start, 5)
    return row


def atomic_write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="new local output directory")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        parser.error("choose a new output directory")
    out.mkdir(parents=True)
    (out / "sources").mkdir()
    enc = tiktoken.get_encoding(ENCODING)
    calibration = json.loads((HERE / "calibration.json").read_text())
    profile = calibration["selected_profile"]
    plan = schedule()
    run = {
        "model": MODEL, "reasoning_effort": "low", "client_profile": profile,
        "cli": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "platform": platform.platform(), "python": platform.python_version(), "encoding": ENCODING,
        "tiktoken": tiktoken.__version__, "started_utc": now(), "rounds": 4,
        "rounds_by_task": {t: 4 for t in TASKS}, "limits": LIMITS, "variants": VARIANTS,
        "schedule": plan, "prompt_task_sha256": {t: digest(PROMPTS[t]) for t in TASKS},
        "first_request_sha256": {arm: {t: digest(prompt(t, arm)) for t in TASKS} for arm in ("python", "compact")},
        "trials": [],
    }
    manifest = out / "results.json"
    atomic_write(manifest, run)  # Freeze the full schedule and first prompts before sending a task.
    seen = {}
    for entry in plan:
        row = run_trial(entry, profile, out, enc, seen)
        run["trials"].append(row)
        atomic_write(manifest, run)
        print(row["round"], row["task"], row["arm"], len(row["attempts"]), row["passed"], row["wall_s"], flush=True)
    run["finished_utc"] = now()
    atomic_write(manifest, run)


if __name__ == "__main__":
    main()
