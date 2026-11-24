import json

def nonnegative(n):
    return type(n) is int and n >= 0

events = {}
with open("events.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        run, seq, kind = (event.get(key) for key in ("run", "seq", "type"))
        if (isinstance(run, str) and run and nonnegative(seq)
                and kind in ("item.completed", "turn.completed", "turn.failed")):
            events.setdefault(run, {}).setdefault(seq, event)

metrics = ("commands", "input_tokens", "output_tokens")
totals = dict.fromkeys(("ok", "failed", "open", *metrics), 0)
runs = []
for run, entries in sorted(events.items()):
    report = dict(run=run, status="open", last_message=None, **dict.fromkeys(metrics, 0))
    for _, event in sorted(entries.items()):
        kind = event["type"]
        if kind == "item.completed":
            item = event.get("item")
            if isinstance(item, dict):
                if item.get("type") == "command_execution":
                    report["commands"] += 1
                elif item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    report["last_message"] = item["text"]
            continue
        report["status"] = "ok" if kind == "turn.completed" else "failed"
        usage = event.get("usage")
        if report["status"] == "ok" and isinstance(usage, dict):
            for key in metrics[1:]:
                n = usage.get(key)
                if nonnegative(n):
                    report[key] = n
        break
    runs.append(report)
    totals[report["status"]] += 1
    for key in metrics:
        totals[key] += report[key]

wj({"runs": runs, "totals": totals})