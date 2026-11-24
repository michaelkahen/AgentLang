"""Measure both languages with the same four programs requested in one turn."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import tiktoken
from benchmarks.patterns.generation.client import HERE as CARDS, MODEL, invoke
from benchmarks.patterns.generation.run import ENCODING, PROMPTS, TASKS, VARIANTS, atomic_write, grade, now


def prompt(arm, pending, feedback):
    language = "Python" if arm == "python" else "AgentLang"
    parts = [f"Write concise standalone {language} programs. Standard library allowed. "
             "No tools or Markdown. Start each program with its exact @@ name line.",
             (CARDS / "operations.txt").read_text().strip()]
    if arm == "compact":
        parts.append((CARDS / "syntax.txt").read_text().strip())
    for name in pending:
        parts.append(f"@@ {name}\n{PROMPTS[name]}")
        if name in feedback:
            problem, previous = feedback[name]
            parts.append(f"Repair: {problem}\nPrevious source:\n{previous}")
    return "\n\n".join(parts)


def split_response(response, expected):
    headers = list(re.finditer(r"^@@ ([a-z_]+)[ \t]*\r?$", response, re.MULTILINE))
    names = [m[1] for m in headers]
    if (set(names) != set(expected) or len(names) != len(expected)
            or response[:headers[0].start()].strip()):
        return {}
    stops = [m.start() for m in headers[1:]] + [len(response)]
    return {m[1]: response[m.end():stop].strip("\r\n") for m, stop in zip(headers, stops)}


def run_batch(arm, number, order, out, encoding):
    start = time.perf_counter()
    deadline = start + 270
    pending, accepted, feedback, attempts = list(order), {}, {}, []
    for index in range(1, 4):
        remaining = deadline - time.perf_counter()
        if not pending or remaining <= 0:
            break
        request = prompt(arm, pending, feedback)
        response, metrics, issue = invoke(request, "lean", min(120, remaining))
        path = f"{arm}-r{number}-a{index}.txt"
        (out / path).write_text(response, encoding="utf-8")
        programs = split_response(response, pending) if not issue else {}
        checks = {}
        for name in pending:
            source = programs.get(name, "")
            if issue or not programs:
                problem, verdicts = issue or "Use exactly one @@ name line per requested program.", {}
            else:
                problem, verdicts = grade(source, name, arm, VARIANTS, deadline)
            checks[name] = {"problem": problem, "fixtures": verdicts}
            if problem:
                feedback[name] = (problem, source)
            else:
                accepted[name] = (index, source)
        pending = [name for name in pending if name not in accepted]
        attempts.append({"requested": list(checks), "response": path, "request_sha256": digest(request),
                         "response_sha256": digest(response), "prompt_tokens": len(encoding.encode(request)),
                         "visible_response_tokens": len(encoding.encode(response)), "client": metrics,
                         "checks": checks})
    elapsed = time.perf_counter() - start
    # Run the held-out audit after stopping the clock, without model feedback.
    audit = {}
    for name, (attempt, source) in accepted.items():
        problem, checks = grade(source, name, arm, ("audit",), time.perf_counter() + 30)
        audit[name] = {"attempt": attempt, "checks": checks, "passed": problem is None}
    return {"arm": arm, "round": number, "order": list(order), "attempts": attempts,
            "passed": len(accepted) == len(order), "wall_s": round(elapsed, 5), "audit": audit}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory to hold exact responses and measurements")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    encoding = tiktoken.get_encoding(ENCODING)
    plan = [(1, "python", TASKS), (1, "compact", TASKS),
            (2, "compact", TASKS[2:] + TASKS[:2]), (2, "python", TASKS[2:] + TASKS[:2])]
    results = {"model": MODEL, "profile": "lean", "encoding": ENCODING, "started_utc": now(),
               "schedule": [{"round": i, "arm": arm, "order": order,
                             "first_request_sha256": digest(prompt(arm, order, {}))}
                            for i, arm, order in plan],
               "limits": {"attempts": 3, "request_s": 120, "batch_s": 270}, "batches": []}
    manifest = out / "results.json"
    atomic_write(manifest, results)
    for i, arm, order in plan:
        row = run_batch(arm, i, order, out, encoding)
        results["batches"].append(row)
        atomic_write(manifest, results)
        print(i, arm, row["passed"], row["wall_s"], flush=True)
    results["finished_utc"] = now()
    atomic_write(manifest, results)


if __name__ == "__main__":
    main()
