"""Verify a completed batch archive and replay accepted scripts with no model requests."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import tiktoken
from agentlang import compile_python, compile_source
from benchmarks.patterns.batch.run import digest, prompt, split_response
from benchmarks.patterns.evaluation.cases import TASKS, TRACE_NAME, matches, record, totals
from benchmarks.patterns.generation.run import ENCODING, VARIANTS, grade
from benchmarks.patterns.generation.verify import require


def planned_schedule():
    normal = list(TASKS)
    rotated = normal[2:] + normal[:2]
    return [
        {"round": r, "arm": arm, "order": order, "first_request_sha256": digest(prompt(arm, order, {}))}
        for r, arm, order in [(1, "python", normal), (1, "compact", normal),
                              (2, "compact", rotated), (2, "python", rotated)]
    ]


def client_problem(client):
    if client["timed_out"]:
        return "Generation exceeded the time limit."
    if client["exit"] or client["service_usage"] is None or not client["message_count"]:
        return "The client returned no complete program."
    if client["non_message_items"] or client["message_count"] != 1:
        return "Return only one source response without tool calls."
    return None


def strict_probe(source, arm):
    compile_program = compile_python if arm == "python" else compile_source
    probe = ROOT / "benchmarks/patterns/evaluation/strict-json.jsonl"
    expected = {"runs": [record("real", "ok", input_tokens=3, output_tokens=7)],
                "totals": totals(1, 0, 0, 0, 3, 7)}
    with tempfile.TemporaryDirectory() as directory:
        cwd = Path(directory)
        (cwd / "events.jsonl").write_bytes(probe.read_bytes())
        (cwd / "candidate.py").write_text(compile_program(source), encoding="utf-8")
        cmd = [sys.executable, "-I", "-B", "candidate.py"]
        if sys.platform == "darwin":
            policy = ("(version 1)(allow default)(deny network*)(deny file-write*)"
                      f"(allow file-write* (subpath {json.dumps(str(cwd.resolve()))}))")
            cmd = ["/usr/bin/sandbox-exec", "-p", policy, *cmd]
        out = subprocess.run(cmd, cwd=cwd, input=b"", capture_output=True, timeout=10,
                             env={"PATH": os.defpath, "LC_ALL": "C", "HOME": directory})
        return out.returncode == 0 and matches(out.stdout, expected)


def native_equivalence(source, task):
    """Check whether the accepted compact source has native Python syntax and the same prepared AST."""
    result = {"native_python_grammar": False, "prepared_ast_equal": None, "native_fixtures": {}}
    try:
        compile(source, "<original>", "exec")
    except SyntaxError:
        return result
    result["native_python_grammar"] = True
    compact_tree = ast.dump(ast.parse(compile_source(source)), include_attributes=False)
    native_tree = ast.dump(ast.parse(compile_python(source)), include_attributes=False)
    result["prepared_ast_equal"] = compact_tree == native_tree
    if result["prepared_ast_equal"]:
        for variant in (*VARIANTS, "audit"):
            problem, _ = grade(source, task, "python", (variant,), time.perf_counter() + 20)
            result["native_fixtures"][variant] = problem or "pass"
    return result


def verify_batch(batch, directory, enc):
    arm, round_no = batch["arm"], batch["round"]
    label = f"{arm} round {round_no}"
    pending, accepted, feedback = list(batch["order"]), {}, {}
    require(1 <= len(batch["attempts"]) <= 3, f"{label}: invalid number of attempts")
    for index, attempt in enumerate(batch["attempts"], 1):
        stage = f"{label} attempt {index}"
        require(pending and attempt["requested"] == list(attempt["checks"]) == pending,
                f"{stage}: requested programs differ from the outstanding work")
        request = prompt(arm, pending, feedback)
        filename = f"{arm}-r{round_no}-a{index}.txt"
        require(attempt["response"] == filename, f"{stage}: unexpected response filename")
        response = (directory / filename).read_bytes().decode("utf-8")
        for kind, text, token_key in [("request", request, "prompt_tokens"),
                                      ("response", response, "visible_response_tokens")]:
            require(digest(text) == attempt[f"{kind}_sha256"], f"{stage}: {kind} digest mismatch")
            require(len(enc.encode(text)) == attempt[token_key], f"{stage}: {kind} token count mismatch")
        issue = client_problem(attempt["client"])
        programs = {} if issue else split_response(response, pending)
        for task in pending:
            source = programs.get(task, "")
            if issue or not programs:
                problem, checks = issue or "Use exactly one @@ name line per requested program.", {}
            else:
                problem, checks = grade(source, task, arm, VARIANTS, time.perf_counter() + 40)
            require(attempt["checks"][task] == {"problem": problem, "fixtures": checks},
                    f"{stage} {task}: acceptance or fixture mismatch; replay yielded {problem or 'pass'} {checks}")
            if problem:
                feedback[task] = (problem, source)
            else:
                accepted[task] = index, source, checks
        pending = [task for task in pending if task not in accepted]

    require(batch["passed"] is (not pending), f"{label}: batch acceptance mismatch")
    require(set(batch["audit"]) == set(accepted), f"{label}: audited programs differ from accepted sources")
    rows = []
    for task, (index, source, first_checks) in accepted.items():
        problem, checks = grade(source, task, arm, ("audit",), time.perf_counter() + 20)
        require(batch["audit"][task] == {"attempt": index, "checks": checks, "passed": problem is None},
                f"{label} {task}: audit mismatch")
        row = {"arm": arm, "round": round_no, "task": task, "accepted_attempt": index,
               "source_sha256": digest(source), "fixtures": {**first_checks, **checks}}
        if arm == "compact":
            row["native_equivalence"] = native_equivalence(source, task)
        if task == TRACE_NAME:
            row["supplemental_strict_json"] = strict_probe(source, arm)
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, nargs="?", default=Path(__file__).parent / "observations/results.json")
    parser.add_argument("--out", type=Path, help="Write per-program replay verdicts and recovered source hashes.")
    args = parser.parse_args()
    run = json.loads(args.results.read_bytes())
    planned = planned_schedule()
    require(run["encoding"] == ENCODING and run.get("finished_utc"), "incomplete archive or unexpected encoding")
    require(run["schedule"] == planned, "archive schedule differs from the preregistered order")
    keys = ("round", "arm", "order")
    require([[r[k] for k in keys] for r in run["batches"]] == [[r[k] for k in keys] for r in planned],
            "recorded batches differ from the planned schedule")
    enc = tiktoken.get_encoding(ENCODING)
    rows = [row for batch in run["batches"] for row in verify_batch(batch, args.results.parent, enc)]
    probes = [r["supplemental_strict_json"] for r in rows if "supplemental_strict_json" in r]
    passed = sum(all(v == "pass" for v in r["fixtures"].values()) for r in rows)
    if args.out:
        report = {"results_sha256": digest(args.results.read_bytes().decode("utf-8")), "programs": rows}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{len(run['batches'])} scheduled batches, {len(rows)} accepted programs, "
          f"{passed} passed all four fixtures, {sum(probes)}/{len(probes)} passed strict JSON.")
    controls = [r["native_equivalence"] for r in rows if "native_equivalence" in r]
    identical = [c for c in controls if c["prepared_ast_equal"]]
    native_passes = sum(all(v == "pass" for v in c["native_fixtures"].values()) for c in identical)
    print(f"{len(identical)}/{len(controls)} AgentLang-arm sources produced identical prepared ASTs "
          f"as native Python; {native_passes}/{len(identical)} passed all four under the native control.")
    return int(passed != len(planned) * len(TASKS) or not all(probes) or native_passes != len(identical))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, IndexError, TypeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Batch verification failed: {error}") from None
