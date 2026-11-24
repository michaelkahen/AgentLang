"""Collect fresh, matched Python and AgentLang attempts and validate each before retrying."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time

import tiktoken

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.pilot.generation.collect import COMMON


HELPERS = (
    "These three helpers are preloaded in both languages. csvrows(path) reads a UTF-8 "
    "CSV into a list of dictionaries with string values. readjson() loads JSON from stdin, "
    "or readjson(path) loads a UTF-8 JSON file. writejson(value) prints one JSON value "
    "and a newline using json.dumps defaults. You can also import Python's standard library."
)
GRAMMAR = (
    "AgentLang accepts ordinary Python. Use its compact forms when helpful. Pipelines "
    "occupy one physical line: x = SRC | STAGE | STAGE, return SRC | STAGE, emit SRC | "
    "STAGE or jsonout SRC | STAGE. emit expr prints expr; jsonout expr calls writejson(expr). "
    "Stages: where EXPR, map EXPR, flat EXPR (flatten one iterable per input), count, sum "
    "[EXPR], mean [EXPR], sort [EXPR] (stable), common N (Counter.most_common result), "
    "first, list. _ denotes the current item. where, map and flat produce generators. "
    "No pipelines nested inside other expressions. Parenthesize any | inside a stage expression."
)
ARMS = ("python", "compact")
VARIANTS = ("base", "edges", "profile")
LIMITS = {"attempts": 3, "attempt_seconds": 90, "trial_seconds": 180, "grading_seconds": 8}
ENCODING = "o200k_base"


def prompt(spec, arm, previous=None, feedback=None, *, require_pipeline=False):
    language = "ordinary Python 3" if arm == "python" else "AgentLang"
    helpers = HELPERS
    if require_pipeline:
        helpers += (" Both languages additionally preload these equivalent short names: "
                    "r() or r(path) is readjson, c(path) is csvrows, and wj(value) is writejson.")
    parts = [f"Write a script in {language}. {COMMON}", helpers, spec]
    if arm == "compact":
        if require_pipeline:
            parts.append(Path(__file__).with_name("short-grammar.txt").read_text(encoding="utf-8").strip())
        else:
            parts.append(GRAMMAR)
    if feedback:
        parts.extend(["The previous attempt failed validation. " + feedback,
                      "Previous source:\n" + (previous or "(no source returned)"),
                      "Return a corrected complete program."])
    return "\n\n".join(parts)


def monitored(command, stdin, cwd, timeout, *, env=None):
    """Get per-child CPU and RSS, including time spent on timeouts."""
    with tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        input_file.write(stdin)
        input_file.seek(0)
        start = time.perf_counter()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=input_file, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        deadline = start + timeout
        timed_out = False
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            if time.perf_counter() >= deadline:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(min(0.015, max(0, deadline - time.perf_counter())))
        process.returncode = os.waitstatus_to_exitcode(status)
        elapsed = time.perf_counter() - start
        stdout.seek(0)
        stderr.seek(0)
        metrics = {
            "wall_s": round(elapsed, 5),
            "cpu_s": round(usage.ru_utime + usage.ru_stime, 5),
            "peak_rss_mib": round(usage.ru_maxrss / (1024**2 if sys.platform == "darwin" else 1024), 3),
            "exit": process.returncode, "timed_out": timed_out,
        }
        return stdout.read(), stderr.read(), metrics


def invoke(request, directory, model, timeout):
    args = ["codex", "--no-daemon", "-a", "never", "exec", "--skip-git-repo-check",
            "--ephemeral", "--ignore-user-config", "-s", "read-only", "-c",
            "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
            "-m", model, "--color", "never", "--json", "-"]
    data, _, metrics = monitored(args, request.encode(), directory, timeout)
    events = []
    for line in data.splitlines():
        try:
            events.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # Interrupted last event can be incomplete on a timeout.
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    messages = [i["text"] for i in items if i.get("type") == "agent_message"]
    non_messages = [i.get("type") for i in items if i.get("type") != "agent_message"]
    usage = [e["usage"] for e in events if e.get("type") == "turn.completed" and e.get("usage")]
    metrics["service_usage"] = {key: sum(u.get(key, 0) for u in usage) for key in usage[0]} if usage else None
    metrics["message_count"] = len(messages)
    metrics["non_message_items"] = non_messages
    if metrics["timed_out"]:
        problem = "The generation attempt exceeded the time limit."
    elif metrics["exit"] or not usage or not messages:
        problem = "The client did not return a complete program."
    elif non_messages or len(messages) != 1:
        problem = "Return a single final source response with no tools or extra messages."
    else:
        problem = None
    return messages[-1] if messages else "", metrics, problem


def valid_json(stream):
    def reject_constant(_):
        raise ValueError("non-finite JSON")
    return json.loads(stream, parse_constant=reject_constant)


def same_json(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_json(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b))
    return a == b


def grade(source, task, arm, deadline, *, require_pipeline=False):
    from agentlang import compile_python, compile_source
    from benchmarks.long.workloads.cases import prepare

    compiler = compile_python if arm == "python" else compile_source
    try:
        program = compiler(source, "<candidate>")
        compile(program, "<candidate>", "exec")
    except (ValueError, SyntaxError) as error:
        line = getattr(error, "lineno", None)
        hint = f" on line {line}" if line else ""
        return "The program did not compile" + hint + ".", {}
    if require_pipeline and arm == "compact":
        from agentlang import count_short_stages
        if count_short_stages(source) == 0:
            return "Use a recognized one-letter collection stage on task data.", {}
    cases = {}
    for variant in VARIANTS:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            case = prepare(task, variant, fixture)
            (fixture / "candidate.py").write_text(program, encoding="utf-8")
            available = min(LIMITS["grading_seconds"], deadline - time.perf_counter())
            if available <= 0:
                return "The trial exceeded its time budget during validation.", cases
            command = [sys.executable, "-I", "-B", "candidate.py"]
            if sys.platform == "darwin":
                policy = ("(version 1)(allow default)(deny network*)(deny file-write*)"
                          f"(allow file-write* (subpath {json.dumps(str(fixture.resolve()))}))")
                command = ["/usr/bin/sandbox-exec", "-p", policy, *command]
            out, err, metrics = monitored(command, case["stdin"], fixture, available,
                                         env={"PATH": os.defpath, "LC_ALL": "C", "HOME": directory})
        if metrics["timed_out"]:
            problem = "execution timed out"
        elif metrics["exit"]:
            error_kind = err.decode(errors="replace").splitlines()[-1:] or [""]
            kind = error_kind[0].split(":", 1)[0]
            problem = "execution raised " + kind if kind.isidentifier() else "execution failed"
        else:
            try:
                problem = None if same_json(valid_json(out), case["expected"]) else "JSON did not match"
            except (UnicodeDecodeError, ValueError):
                problem = "stdout was not one valid JSON value"
        cases[variant] = "pass" if problem is None else problem
        if problem:
            return f"Fixture {variant} failed: {problem}.", cases
    return None, cases


def trial(task, spec, arm, repeat, model, directory, enc, *, require_pipeline=False):
    start = time.perf_counter()
    deadline = start + LIMITS["trial_seconds"]
    row = {"task": task, "arm": arm, "round": repeat, "attempts": [], "passed": False}
    previous = feedback = None
    for index in range(LIMITS["attempts"]):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        request = prompt(spec, arm, previous, feedback, require_pipeline=require_pipeline)
        with tempfile.TemporaryDirectory() as empty:
            source, generation, problem = invoke(request, empty, model, min(remaining, LIMITS["attempt_seconds"]))
        answer_path = None
        if source:
            raw = source.encode()
            extension = ".py" if arm == "python" else ".ag"
            previous_paths = list((directory / "sources").glob(f"*{extension}"))
            path = next((p for p in previous_paths if p.read_bytes() == raw), None)
            if path is None:
                name = f"{task}-{arm}-r{repeat}-a{index + 1}{extension}"
                path = directory / "sources" / name
                path.write_bytes(raw)
            name = path.name
            answer_path = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(Path("sources") / name)
        begin_grade = time.perf_counter()
        checks = {}
        if problem is None:
            problem, checks = grade(source, task, arm, deadline, require_pipeline=require_pipeline)
        uses_shorthand = False
        if arm == "compact" and problem is None:
            from agentlang import compile_python, compile_source
            try:
                uses_shorthand = compile_source(source) != compile_python(source)
            except SyntaxError:
                uses_shorthand = True
        stage_count = None
        if require_pipeline and arm == "compact" and source:
            from agentlang import count_short_stages
            try:
                stage_count = count_short_stages(source)
            except (ValueError, SyntaxError):
                pass
        row["attempts"].append({
            "short_stage_count": stage_count, "attempt": index + 1, "passed": problem is None, "diagnostic": problem,
            "source_path": answer_path, "uses_shorthand": uses_shorthand, "visible_source_tokens": len(enc.encode(source)),
            "prompt_tokens": len(enc.encode(request)), "generation": generation,
            "validation_s": round(time.perf_counter() - begin_grade, 5), "fixtures": checks,
        })
        if problem is None:
            row["passed"] = True
            break
        previous, feedback = source, problem
    row["wall_s"] = round(time.perf_counter() - start, 5)
    return row


def main():
    from benchmarks.long.workloads.cases import TASKS, PROMPTS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory for local source and results")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--model", default="gpt-6.2-sol")
    parser.add_argument("--require-pipeline", action="store_true",
                        help="require a short-form collection pipeline in the AgentLang arm")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    results = directory / "results.json"
    if results.exists() or (directory / "sources").exists():
        parser.error("use a new output directory")
    (directory / "sources").mkdir()
    enc = tiktoken.get_encoding(ENCODING)
    run = {
        "require_short_pipeline": args.require_pipeline,
        "model": args.model, "reasoning_effort": "low", "rounds": args.rounds,
        "limits": LIMITS, "variants": VARIANTS, "encoding": ENCODING, "tiktoken": tiktoken.__version__,
        "cli": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "platform": platform.platform(), "python": platform.python_version(),
        "prompt_task_sha256": {t: hashlib.sha256(PROMPTS[t].encode()).hexdigest() for t in TASKS},
        "trials": [],
    }
    for repeat in range(args.rounds):
        for offset in range(len(TASKS)):
            idx = (repeat + offset) % len(TASKS)
            task = TASKS[idx]
            arms = ARMS if (repeat + idx) % 2 == 0 else ARMS[::-1]
            for arm in arms:
                row = trial(task, PROMPTS[task], arm, repeat + 1, args.model, directory, enc,
                            require_pipeline=args.require_pipeline)
                run["trials"].append(row)
                tmp = results.with_suffix(".tmp")
                tmp.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
                tmp.replace(results)
                print(repeat + 1, task, arm, len(row["attempts"]), row["passed"],
                      row["wall_s"], flush=True)


if __name__ == "__main__":
    main()
