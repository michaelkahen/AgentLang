"""Summarize complete paired single-script and four-script batch measurements."""
import argparse
import json
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent


def metrics(row):
    attempts = row["attempts"]
    clients = [a["generation"] if "generation" in a else a["client"] for a in attempts]
    usage = [c["service_usage"] for c in clients]
    result = {
        "attempts": len(attempts), "passed": int(row["passed"]), "wall_s": row["wall_s"],
        "visible_response_tokens": sum(a["visible_source_tokens"] if "visible_source_tokens" in a
                                       else a["visible_response_tokens"] for a in attempts),
        "prompt": sum(a["prompt_tokens"] for a in attempts),
        "client_cpu_s": sum(c["cpu_s"] for c in clients),
        "peak_client_rss_mib": max(c["peak_rss_mib"] for c in clients),
    }
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
        result[key] = sum(u[key] for u in usage) if all(u is not None for u in usage) else None
    result["total_service"] = (result["input_tokens"] + result["output_tokens"]
                               if result["input_tokens"] is not None else None)
    return result


def aggregate(rows):
    groups = {}
    for arm in ("python", "compact"):
        observed = [metrics(row) for row in rows if row["arm"] == arm]
        if not observed:
            continue
        agg = {key: sum(m[key] for m in observed) if all(m[key] is not None for m in observed) else None
               for key in observed[0] if key != "peak_client_rss_mib"}
        good_times = [m["wall_s"] for m in observed if m["passed"]]
        agg["trials"] = len(observed)
        agg["median_s_to_pass"] = median(good_times) if good_times else None
        agg["median_peak_rss_mib_per_trial"] = median(m["peak_client_rss_mib"] for m in observed)
        groups[arm] = agg
    return groups


def comparisons(rows):
    pairs = {}
    for row in rows:
        arms = pairs.setdefault((row.get("task"), row["round"]), {})
        if row["arm"] in arms:
            raise ValueError("duplicate trial")
        arms[row["arm"]] = metrics(row)
    wins = {"both": 0, "time": 0, "tokens": 0}
    complete = 0
    for arms in pairs.values():
        if len(arms) != 2:
            raise ValueError("unmatched trial")
        p, c = arms["python"], arms["compact"]
        if not p["passed"] or not c["passed"] or p["total_service"] is None or c["total_service"] is None:
            continue
        complete += 1
        faster = c["wall_s"] < p["wall_s"]
        shorter = c["total_service"] < p["total_service"]
        wins["time"] += faster
        wins["tokens"] += shorter
        wins["both"] += faster and shorter
    return {"pairs": len(pairs), "pairs_with_complete_measurements_and_passes": complete, "agentlang_wins": wins}


def scheduled_rows(path, key, fields):
    manifest = json.loads(path.read_text())
    if not manifest.get("finished_utc"):
        raise ValueError(f"Incomplete collection in {path}")
    rows = manifest[key]
    expected = [[s[f] for f in fields] for s in manifest["schedule"]]
    actual = [[r[f] for f in fields] for r in rows]
    if not expected or actual != expected:
        raise ValueError(f"Recorded rows differ from the planned schedule in {path}")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", type=Path, default=HERE / "generation/observations/results.json")
    parser.add_argument("--batch", type=Path, default=HERE / "batch/observations/results.json")
    args = parser.parse_args()
    single = scheduled_rows(args.single, "trials", ("round", "task", "arm"))
    batches = scheduled_rows(args.batch, "batches", ("round", "arm", "order"))
    tasks = dict.fromkeys(r["task"] for r in single)
    report = {
        "single": aggregate(single), "single_paired": comparisons(single),
        "by_task": {task: aggregate([r for r in single if r["task"] == task]) for task in tasks},
        "batch": aggregate(batches), "batch_paired": comparisons(batches),
        "batch_audit": {
            arm: {"scheduled_programs": sum(len(r["order"]) for r in batches if r["arm"] == arm),
                  "passed": sum(a["passed"] for r in batches if r["arm"] == arm for a in r["audit"].values())}
            for arm in ("python", "compact")
        },
        "single_first_two_rounds": aggregate([r for r in single if r["round"] <= 2]),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
