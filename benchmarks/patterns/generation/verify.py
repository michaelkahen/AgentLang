"""Verify the schedule, prompt and source records; replay all four fixtures without feedback."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.patterns.generation.run import ENCODING, VARIANTS, atomic_write, digest, grade, prompt, schedule
import tiktoken


def require(condition, description):
    if not condition:
        raise ValueError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads(args.results.read_text(encoding="utf-8"))
    require(run["schedule"] == schedule(), "schedule differs from the registered order")
    rows = run["trials"]
    require([{k: v for k, v in r.items() if k in ("round", "task", "arm")} for r in rows] == schedule(),
            "recorded trials differ from the planned schedule")
    outcomes = []
    enc = tiktoken.get_encoding(ENCODING)
    for row in rows:
        previous = feedback = None
        outcome = {k: row[k] for k in ("round", "task", "arm")}
        outcome["attempts"] = []
        for attempt in row["attempts"]:
            request = prompt(row["task"], row["arm"], previous, feedback)
            require(digest(request) == attempt["request_sha256"], "request changed")
            require(len(enc.encode(request)) == attempt["prompt_tokens"], "prompt token count changed")
            source = ""
            if attempt["source_path"]:
                path = Path(attempt["source_path"])
                path = (ROOT if path.parts[0] == "benchmarks" else args.results.parent) / path
                source = path.read_text(encoding="utf-8")
                require(digest(source) == attempt["source_sha256"], "source changed")
            require(len(enc.encode(source)) == attempt["visible_source_tokens"], "source token count changed")
            checks = {}
            if source:
                for variant in (*VARIANTS, "audit"):
                    error, _ = grade(source, row["task"], row["arm"], (variant,), time.perf_counter() + 16)
                    checks[variant] = error or "pass"
            passed = bool(checks) and all(x == "pass" for x in checks.values())
            outcome["attempts"].append(dict(attempt=attempt["attempt"], accepted=attempt["passed"],
                                             passed_all_four=passed, checks=checks))
            previous, feedback = source, attempt["diagnostic"]
        outcome["accepted_passes_all_four"] = any(x["accepted"] and x["passed_all_four"] for x in outcome["attempts"])
        outcomes.append(outcome)
    atomic_write(args.out, {"results_manifest_sha256": digest(args.results.read_text(encoding="utf-8")),
                            "variants": [*VARIANTS, "audit"], "results": outcomes})
    passed = sum(r["accepted_passes_all_four"] for r in outcomes)
    print(f"{passed} of {len(rows)} trial sequences passed all fixtures.")
    return int(passed != len(rows))


if __name__ == "__main__":
    raise SystemExit(main())
