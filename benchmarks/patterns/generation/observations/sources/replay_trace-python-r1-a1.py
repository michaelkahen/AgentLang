import json

def nonnegative(n):
    return type(n) is int and n >= 0

events = {}
with open("events.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            e = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(e, dict):
            continue
        run, seq, kind = e.get("run"), e.get("seq"), e.get("type")
        if (isinstance(run, str) and run and nonnegative(seq)
                and kind in ("item.completed", "turn.completed", "turn.failed")):
            events.setdefault(run, {}).setdefault(seq, e)

runs = []
metrics = ("commands", "input_tokens", "output_tokens")
totals = dict.fromkeys(("ok", "failed", "open") + metrics, 0)
for run, by_seq in sorted(events.items()):
    report = dict(run=run, status="open", last_message=None, **dict.fromkeys(metrics, 0))
    for seq in sorted(by_seq):
        e = by_seq[seq]
        if e["type"] == "item.completed":
            item = e.get("item")
            if isinstance(item, dict):
                kind, message = item.get("type"), item.get("text")
                if kind == "agent_message" and isinstance(message, str):
                    report["last_message"] = message
                elif kind == "command_execution":
                    report["commands"] += 1
        else:
            if e["type"] == "turn.failed":
                report["status"] = "failed"
            else:
                report["status"] = "ok"
                usage = e.get("usage")
                if isinstance(usage, dict):
                    for key in metrics[1:]:
                        n = usage.get(key)
                        if nonnegative(n):
                            report[key] = n
            break
    runs.append(report)
    totals[report["status"]] += 1
    for key in metrics:
        totals[key] += report[key]

wj(dict(runs=runs, totals=totals))