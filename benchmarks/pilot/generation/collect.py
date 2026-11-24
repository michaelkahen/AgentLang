"""Collect fresh Codex responses; this command never executes a response."""
import argparse
import json
from pathlib import Path
import platform
import resource
import subprocess
import tempfile
import time

import tiktoken


TASKS = {
    "late_flights": (
        "Read the UTF-8 CSV data/tweets.csv with header airline,airline_sentiment,negativereason. "
        "Print the integer count of rows where airline equals 'US Airways', airline_sentiment "
        "equals 'negative', and negativereason equals 'Late Flight'."
    ),
    "goal_gap": (
        "Read the UTF-8 CSV data/projects.csv with header state,usd_goal_real. For each of the "
        "two states 'failed' and 'successful' there is at least one row. The goal field is "
        "numeric. Subtract the mean goal of successful projects from the mean goal of failed "
        "projects. Ignore other states. Print the difference to exactly two decimal places."
    ),
    "word_counts": (
        "Read a JSON array of strings from stdin. Split the strings on Python-style whitespace. "
        "Print the most frequent word across all strings, breaking ties by earliest occurrence. "
        "There is at least one word. Preserve case and punctuation."
    ),
    "sort_scores": (
        "Read a JSON array of [string, number] pairs from stdin. Stable-sort ascending by "
        "the second element of each pair. Print the resulting JSON array using Python "
        "json.dumps defaults."
    ),
}
GRAMMAR = """This language accepts ordinary Python and the following shorthand. Use its compact forms when helpful.
A pipeline occupies one physical line: x = SRC | STAGE | STAGE, emit SRC | STAGE, or jsonout SRC | STAGE. emit expr prints the expression; jsonout expr prints json.dumps(expr). Stages: where EXPR, map EXPR, flat EXPR (flatten one iterable per input), count, sum [EXPR], mean [EXPR], sort [EXPR] (stable), common N (Counter.most_common result), first, list. _ is the current item. csvrows(path) reads a UTF-8 CSV into a list of dictionaries. readjson() reads stdin; readjson(path) reads UTF-8 JSON. No stages inside parentheses or nested expressions; parenthesize any | inside a stage expression. Ordinary Python assignments, imports, loops, comprehensions and formatting are allowed. Shorthand helpers require no imports."""
COMMON = (
    "Return only the complete, concise runnable source code. Use no tools, Markdown, or "
    "explanation. Use the standard library only. Handle all inputs matching the specification, "
    "and write only the specified output followed by a newline."
)


def make_prompt(task, arm):
    language = "Python 3" if arm == "python" else "the compact language specified below"
    request = f"Write a script in {language}. {COMMON}\n\n{TASKS[task]}"
    return request if arm == "python" else request + "\n\n" + GRAMMAR


def cpu_time():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def collect(model, task, arm, directory, timeout, enc):
    prompt = make_prompt(task, arm)
    cmd = ["codex", "--no-daemon", "-a", "never", "exec", "--skip-git-repo-check",
           "--ephemeral", "--ignore-user-config", "-s", "read-only", "-c",
           "project_doc_max_bytes=0", "-c", 'model_reasoning_effort="low"',
           "-m", model, "--color", "never", "--json", "-"]
    cpu_start = cpu_time()
    start = time.perf_counter()
    try:
        completed = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                                   cwd=directory, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"error": "CLI timed out", "wall_s": time.perf_counter() - start}
    elapsed = time.perf_counter() - start
    cpu = cpu_time() - cpu_start
    events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    usage = next((e["usage"] for e in events if e["type"] == "turn.completed"), None)
    items = [e["item"] for e in events if e["type"] == "item.completed"]
    texts = [i["text"] for i in items if i["type"] == "agent_message"]
    source = texts[-1] if texts else ""
    errors = [e.get("message", e.get("error", {}).get("message"))
              for e in events if e["type"] in ("error", "turn.failed")]
    row = {
        "wall_s": round(elapsed, 4),
        "client_cpu_s": round(cpu, 4),
        "user_prompt_tokens_o200k": len(enc.encode(prompt)),
        "visible_source_tokens_o200k": len(enc.encode(source)),
        "source": source,
        "usage": usage,
        "non_message_items": [i["type"] for i in items if i["type"] != "agent_message"],
        "message_count": len(texts),
    }
    if errors or not usage or completed.returncode:
        row["error"] = errors or f"No successful completion (exit {completed.returncode})"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new JSON results file")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--model", default="gpt-6.2-sol")
    args = parser.parse_args()
    if args.out.exists() or args.rounds < 1:
        parser.error("provide a new output path and one or more rounds")
    enc = tiktoken.get_encoding("o200k_base")
    run = {
        "model": args.model, "reasoning_effort": "low",
        "codex": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "platform": platform.platform(), "rounds": args.rounds, "tiktoken": tiktoken.__version__,
        "grammar_tokens_o200k": len(enc.encode(GRAMMAR)),
        "tasks": TASKS, "common": COMMON, "grammar": GRAMMAR, "trials": [],
    }
    tasks = list(TASKS)
    with tempfile.TemporaryDirectory() as directory:
        for repeat in range(args.rounds):
            # Rotate task order, and alternate the starting arm within and across rounds.
            for offset in range(len(tasks)):
                idx = (repeat + offset) % len(tasks)
                task = tasks[idx]
                arms = ("python", "compact") if (repeat + idx) % 2 == 0 else ("compact", "python")
                for arm in arms:
                    row = collect(args.model, task, arm, directory, args.timeout, enc)
                    run["trials"].append({"round": repeat + 1, "task": task, "arm": arm, **row})
                    args.out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
                    print(repeat + 1, task, arm, row["wall_s"], row.get("error", "ok"), flush=True)


if __name__ == "__main__":
    main()
