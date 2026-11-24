import json

def natural(value):
    return type(value) is int and value >= 0

def reject_constant(value):
    raise ValueError(value)

events = {}
with open("events.jsonl", encoding="utf-8") as lines:
    for line in lines:
        try:
            event = json.loads(line, parse_constant=reject_constant)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        run, seq, kind = (event.get(key) for key in ("run", "seq", "type"))
        if (isinstance(run, str) and run and natural(seq)
                and kind in ("item.completed", "turn.completed", "turn.failed")):
            events.setdefault(run, {}).setdefault(seq, event)

metrics = ("commands", "input_tokens", "output_tokens")
totals = dict.fromkeys(("ok", "failed", "open", *metrics), 0)
runs = []
for run, kept in sorted(events.items()):
    row = dict(run=run, status="open", last_message=None, **dict.fromkeys(metrics, 0))
    for seq in sorted(kept):
        event = kept[seq]
        kind = event["type"]
        if kind == "item.completed":
            item = event.get("item")
            if isinstance(item, dict):
                if item.get("type") == "command_execution":
                    row["commands"] += 1
                elif item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    row["last_message"] = item["text"]
            continue
        row["status"] = "ok" if kind == "turn.completed" else "failed"
        usage = event.get("usage")
        if row["status"] == "ok" and isinstance(usage, dict):
            for key in metrics[1:]:
                value = usage.get(key)
                if natural(value):
                    row[key] = value
        break
    runs.append(row)
    totals[row["status"]] += 1
    for key in metrics:
        totals[key] += row[key]

wj(dict(runs=runs, totals=totals))