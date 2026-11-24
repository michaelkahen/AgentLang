"""Frozen held-out workload for the mined-patterns experiment."""

import json
import random
from pathlib import Path

from benchmarks.long.workloads.cases import PROMPTS as PILOT_PROMPTS, matches, prepare as prepare_pilot

TRACE_NAME = "replay_trace"
TRACE_PROMPT = """Recover a per-run report from interleaved, replayed agent events in events.jsonl in cwd (UTF-8 JSON Lines). Skip malformed JSON and values other than objects. A valid envelope has a nonempty string run, a nonnegative integer seq (exclude bool), and a type of 'item.completed', 'turn.completed', or 'turn.failed'. For each (run,seq) keep the first valid envelope in file order, even if its payload is unusable; ignore duplicates. Replay each run's kept events by ascending seq; stop after the first terminal event (turn.completed or turn.failed). For an item.completed with a dict item, a type of 'agent_message' and a string text replaces the last message (including empty strings); a type of 'command_execution' increments commands. For turn.completed, status is 'ok'; if usage is a dict, read input_tokens and output_tokens independently, accepting only nonnegative integers (exclude bool), otherwise use zero. For turn.failed set status 'failed' and keep token counts zero. Runs without a terminal have status 'open' and zero tokens. Print one JSON object with 'runs': a list of objects with keys run, status, last_message (null when absent), commands, input_tokens and output_tokens; sort the list by run ascending. Also include 'totals': an object with keys ok, failed, open (run counts), commands, input_tokens and output_tokens (sums across runs). Empty input gives an empty list and six zero totals."""
PROMPTS = {**PILOT_PROMPTS, TRACE_NAME: TRACE_PROMPT}
TASKS = tuple(PROMPTS)


def event(run, seq, kind, **payload):
    return {"run": run, "seq": seq, "type": kind, **payload}


def item(run, seq, kind, **fields):
    return event(run, seq, "item.completed", item={"type": kind, **fields})


def record(run, status, message=None, commands=0, input_tokens=0, output_tokens=0):
    return dict(run=run, status=status, last_message=message, commands=commands,
                input_tokens=input_tokens, output_tokens=output_tokens)


def totals(ok=0, failed=0, open_count=0, commands=0, input_tokens=0, output_tokens=0):
    return dict(ok=ok, failed=failed, open=open_count, commands=commands,
                input_tokens=input_tokens, output_tokens=output_tokens)


def small_trace(variant):
    # Expected rows below are hand-specified, independently of decoding or sorting the stream.
    if variant == "base":
        lines = [
            event("gamma", 8, "turn.failed"), item("beta", 2, "agent_message", text="ready"),
            event("beta", 4, "turn.completed", usage={"input_tokens": 12, "output_tokens": 4}),
            item("alpha", 5, "agent_message", text="still working"),
            item("beta", 1, "command_execution"), item("beta", 2, "agent_message", text="duplicate"),
            item("beta", 5, "command_execution"), item("gamma", 7, "agent_message", text="bad input"),
            event("gamma", 10, "turn.completed", usage={"input_tokens": 100}),
        ]
        return lines, {"runs": [record("alpha", "open", "still working"),
                                record("beta", "ok", "ready", 1, 12, 4),
                                record("gamma", "failed", "bad input")],
                       "totals": totals(1, 1, 1, 1, 12, 4)}
    if variant == "edges":
        # These raw strings are malformed JSON; other scalar/object entries below are valid JSON.
        lines = ["{", "null", "[]", " ", "{}", event("", 0, "turn.failed"),
                 event("unseen", False, "turn.failed"), event("unseen", -1, "turn.completed"),
                 event("unseen", 1.0, "item.completed"), event("unseen", 5, "thread.started")]
        return lines, {"runs": [], "totals": totals()}
    if variant == "audit":
        lines = [
            item("é", 6, "agent_message", text="wrong"), event("Z", 2, "turn.failed"),
            event("a", 3, "turn.completed", usage={"input_tokens": True, "output_tokens": 7}),
            event("Z", 0, "thread.started"), item("Z", 0, "command_execution"),
            event("é", 3, "turn.completed", usage={"input_tokens": 11, "output_tokens": -1}),
            event("é", 3, "turn.failed"), item("é", 1, "agent_message", text="discarded"),
            item("é", 2, "agent_message", text=""), item("a", 0, "agent_message", text=None),
            event("a", 1, "item.completed", item=[]), item("a", 1, "command_execution"),
            item("mix", 4, "command_execution"), event("mix", 3, "item.completed", item=None),
            event("b", 0, "turn.completed", usage="wrong"), event("mix", True, "turn.failed"),
            event("Z", 1, "turn.failed"), item("Z", 2, "agent_message", text="ignored"),
            "{truncated",
        ]
        expected = {"runs": [record("Z", "failed", commands=1), record("a", "ok", output_tokens=7),
                             record("b", "ok"), record("mix", "open", commands=1),
                             record("é", "ok", "", input_tokens=11)],
                    "totals": totals(3, 1, 1, 2, 11, 7)}
        return lines, expected
    raise ValueError(f"unknown fixture variant {variant!r}")


def profile_trace():
    # Construct from known run histories, then corrupt the wire order; never replay it to get the oracle.
    events, duplicates, runs = [], [], []
    for index in range(1200):
        name = f"job-{index:04d}"
        msg = f"result {index} ✓"
        events.extend([item(name, 0, "agent_message", text="start"), item(name, 1, "command_execution"),
                       item(name, 2, "agent_message", text=msg)])
        if index % 3 == 0:
            n = 13 * index + 5
            events.extend([event(name, 7, "turn.completed", usage={"input_tokens": n, "output_tokens": index}),
                           item(name, 8, "command_execution")])
            runs.append(record(name, "ok", msg, 1, n, index))
        elif index % 3 == 1:
            events.extend([event(name, 7, "turn.failed"), item(name, 8, "agent_message", text="late")])
            runs.append(record(name, "failed", msg, 1))
        else:
            events.append(item(name, 6, "command_execution"))
            runs.append(record(name, "open", msg, 2))
        duplicates.extend([item(name, 2, "agent_message", text="old replay"), event(name, 1, "turn.failed")])
    rng = random.Random(77011)
    rng.shuffle(events)
    rng.shuffle(duplicates)
    # Closed forms for 400 completed jobs with indices 0,3,...,1197: sum(indices) = 239400.
    return [*events, "{", "[]", *duplicates, "{truncated"], {
        "runs": runs, "totals": totals(400, 400, 400, 1600, 3_114_200, 239_400),
    }


def prepare(task, variant, directory):
    """Create the input files and return stdin bytes and the expected JSON value."""
    if task != TRACE_NAME:
        return prepare_pilot(task, variant, directory)
    lines, expected = profile_trace() if variant == "profile" else small_trace(variant)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "events.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for line in lines:
            stream.write(line if isinstance(line, str) else json.dumps(line, ensure_ascii=False))
            stream.write("\n")
    return {"stdin": b"", "expected": expected}
