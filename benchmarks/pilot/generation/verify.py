"""Execute reviewed trial source against two independent fixture sets, then summarize."""
import argparse
import json
from pathlib import Path
import shutil
from statistics import mean, median
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def prepare_cases(base, alternate):
    examples = ROOT / "examples"
    shutil.copytree(examples / "data", base / "data")
    for f in examples.glob("*.in"):
        shutil.copy(f, base / f.name)
    for f in examples.glob("*.out"):
        shutil.copy(f, base / f.name)
    data = alternate / "data"
    data.mkdir()
    (data / "tweets.csv").write_text(
        'airline,airline_sentiment,negativereason\n'
        'US Airways,neutral,Late Flight\n'
        'US Airways,negative,"Late Flight, Delayed"\n'
        'US Airways,negative,late flight\n', encoding="utf-8")
    (data / "projects.csv").write_text(
        "state,usd_goal_real\nfailed,0\nsuccessful,10\nfailed,3.5\ncanceled,900\n",
        encoding="utf-8")
    (alternate / "word_counts.in").write_text(
        '["", "é!\\tWord", "Word  é!", "word", " "]\n', encoding="utf-8")
    (alternate / "sort_scores.in").write_text(
        '[["é", -2], ["b", 0], ["a", -2], ["x", 0.25]]\n', encoding="utf-8")
    for task, result in {
        "late_flights": "0", "goal_gap": "-8.25", "word_counts": "é!",
        "sort_scores": json.dumps([["é", -2], ["a", -2], ["b", 0], ["x", 0.25]]),
    }.items():
        (alternate / f"{task}.out").write_text(result + "\n", encoding="utf-8")


def score(source, task, directory):
    (directory / "trial.py").write_text(source, encoding="utf-8")
    data = directory / (task + ".in")
    expected = (directory / (task + ".out")).read_bytes()
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "trial.py"], cwd=directory,
            input=data.read_bytes() if data.exists() else b"", capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        return "timeout"
    if completed.returncode:
        return completed.stderr.decode(errors="replace").strip().splitlines()[-1]
    return "pass" if completed.stdout == expected else "stdout mismatch"


def summarize(rows):
    for arm in ("python", "compact"):
        trials = [r for r in rows if r["arm"] == arm]
        network_ok = [r for r in trials if r.get("usage")]
        def usage(key):
            return sum(r["usage"].get(key, 0) for r in network_ok)

        def med(key):
            return round(median(r[key] for r in network_ok), 4) if network_ok else None

        print(json.dumps({
            "arm": arm, "attempts": len(trials), "correct_on_both": sum(r["passed"] for r in trials),
            "wall_median_s": med("wall_s"), "cli_cpu_median_s": med("client_cpu_s"),
            "wall_mean_s": round(mean(r["wall_s"] for r in network_ok), 4) if network_ok else None,
            "total_source_tokens_o200k": sum(r["visible_source_tokens_o200k"] for r in network_ok),
            "total_user_prompt_tokens_o200k": sum(r["user_prompt_tokens_o200k"] for r in network_ok),
            "total_server_input_tokens": usage("input_tokens"),
            "total_cached_input_tokens": usage("cached_input_tokens"),
            "total_server_output_tokens": usage("output_tokens"),
            "total_reasoning_tokens": usage("reasoning_output_tokens"),
        }, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="review model programs in this JSON before running")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from agentlang import compile_source
    run = json.loads(args.input.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp) / "base"
        alternate = Path(temp) / "alternate"
        base.mkdir()
        alternate.mkdir()
        prepare_cases(base, alternate)
        for row in run["trials"]:
            start = time.perf_counter()
            try:
                if row.get("error") or row.get("non_message_items") or row["message_count"] != 1:
                    raise ValueError("not a successful single no-tool completion")
                source = row["source"]
                if row["arm"] == "compact":
                    source = compile_source(source)
                row["fixture_verdicts"] = {
                    name: score(source, row["task"], directory)
                    for name, directory in [("base", base), ("alternate", alternate)]
                }
                row["passed"] = all(v == "pass" for v in row["fixture_verdicts"].values())
            except (ValueError, SyntaxError) as err:
                row["fixture_verdicts"] = {"error": str(err)}
                row["passed"] = False
            row["verification_s"] = round(time.perf_counter() - start, 4)
    args.out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    summarize(run["trials"])


if __name__ == "__main__":
    main()
