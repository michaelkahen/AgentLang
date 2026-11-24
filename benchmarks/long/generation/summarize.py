"""Summarize all measured attempts, including errors and incomplete turn accounting."""
from argparse import ArgumentParser
from collections import Counter
import json
from pathlib import Path
from statistics import median


def by_arm(rows):
    observations = {}
    for arm in ("python", "compact"):
        trials = [r for r in rows if r["arm"] == arm]
        attempts = [a for r in trials for a in r["attempts"]]
        successful = [r["wall_s"] for r in trials if r["passed"]]
        usages = [a["generation"]["service_usage"] for a in attempts]
        # A zero is reported only when zero is measured. Covers all returned turns.
        known = [u for u in usages if u is not None]
        service = Counter()
        for usage in known:
            service.update(usage)
        observations[arm] = {
            "trials": len(trials), "attempts": len(attempts), "passed": len(successful),
            "first_pass": sum(r["attempts"][0]["passed"] for r in trials if r["attempts"]),
            "source_tokens": sum(a["visible_source_tokens"] for a in attempts),
            "prompt_tokens": sum(a["prompt_tokens"] for a in attempts),
            "elapsed_s_all": round(sum(r["wall_s"] for r in trials), 4),
            "median_time_to_pass_s": round(median(successful), 4) if successful else None,
            "known_usage_attempts": len(known), "unknown_usage_attempts": len(attempts) - len(known),
            "service_tokens_reported": dict(service),
            "service_input_plus_output_reported": (
                service["input_tokens"] + service["output_tokens"] if known else None),
            "client_cpu_s_all": round(sum(a["generation"]["cpu_s"] for a in attempts), 4),
            "median_client_peak_rss_mib_per_attempt": (
                round(median(a["generation"]["peak_rss_mib"] for a in attempts), 3)
                if attempts else None),
            "validation_s_all": round(sum(a["validation_s"] for a in attempts), 4),
            "passing_programs_using_shorthand": (
                sum(a.get("uses_shorthand", False) and a["passed"] for a in attempts)
                if arm == "compact" else None),
            "attempts_with_counted_short_stages": (
                sum((a.get("short_stage_count") or 0) > 0 for a in attempts)
                if any(a.get("short_stage_count") is not None for a in attempts) else None),
        }
    return observations


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    rows = data["trials"]
    tasks = dict.fromkeys(row["task"] for row in rows)
    print(json.dumps({"overall": by_arm(rows),
                      "tasks": {task: by_arm([r for r in rows if r["task"] == task])
                                for task in tasks}}, indent=2))


if __name__ == "__main__":
    main()
