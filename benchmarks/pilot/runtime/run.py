"""Compare the Python and AgentLang examples. Run with --help for options."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from scale import prepare_examples

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, default=ROOT / "examples")
    parser.add_argument("--case", action="append", help="Run this example (repeatable).")
    parser.add_argument("--runs", type=int, default=12, help="Measured runs per mode per case.")
    parser.add_argument("--warmups", type=int, default=1, help="Unmeasured runs per mode per case.")
    parser.add_argument("--scale", type=int, default=1, help="Repeat the bundled data records this many times.")
    parser.add_argument("--seed", type=int, default=42, help="Seed for mode ordering.")
    parser.add_argument("--output", type=Path, help="Result JSON. Defaults to results/{seed,scaled}.json beside this harness.")
    args = parser.parse_args()
    if args.runs < 1 or args.scale < 1 or args.warmups < 0:
        parser.error("--runs and --scale must be positive and --warmups must be nonnegative")
    if sys.platform not in {"darwin", "linux"}:
        parser.error("Per-process peak RSS measurement supports macOS and Linux.")
    if args.output is None:
        filename = "seed.json" if args.scale == 1 else "scaled.json"
        args.output = HERE / "results" / filename
    return args


def file_stats(path, encoding):
    data = path.read_bytes()
    return {
        "bytes": len(data),
        "tokens": len(encoding.encode_ordinary(data.decode("utf-8"))),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def cpu_model():
    if sys.platform == "darwin":
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    else:
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text().splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "model name":
                    return value.strip()
    return platform.processor() or platform.machine()


def trial(command, cwd, env, input_path, expected):
    with input_path.open("rb") as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        started = time.perf_counter_ns()
        with subprocess.Popen(command, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr) as child:
            _, status, usage = os.wait4(child.pid, 0)
            elapsed = time.perf_counter_ns() - started
            child.returncode = os.waitstatus_to_exitcode(status)

        if child.returncode:
            stderr.seek(0)
            raise RuntimeError(f"{command} exited {child.returncode}\n{stderr.read(4096).decode(errors='replace')}")
        stdout.seek(0)
        actual = stdout.read(len(expected) + 1)
        if actual != expected:
            raise ValueError(f"{command}: stdout differs from fixture\nexpected {expected[:256]!r}\nreceived {actual[:256]!r}")

    return {
        "wall_ms": elapsed / 1_000_000,
        "cpu_ms": (usage.ru_utime + usage.ru_stime) * 1000,
        "peak_rss_mib": usage.ru_maxrss / (1024**2 if sys.platform == "darwin" else 1024),
    }


def orders(modes, rounds, rng):
    """Every full block places each mode in each position exactly once."""
    cycle = list(modes)
    for index in range(rounds):
        offset = index % len(cycle)
        if offset == 0:
            rng.shuffle(cycle)
        yield cycle[offset:] + cycle[:offset]


def describe(samples):
    summary = {}
    for metric in ("wall_ms", "cpu_ms", "peak_rss_mib"):
        values = [sample[metric] for sample in samples]
        if len(values) > 1:
            q1, _, q3 = statistics.quantiles(values, method="inclusive")
        else:
            q1 = q3 = values[0]
        summary[metric] = {
            "min": min(values), "p25": q1, "median": statistics.median(values),
            "p75": q3, "max": max(values),
        }
    return summary


def token_comparison(compact, reference):
    saved = reference - compact
    return {
        "compact_tokens": compact,
        "reference_tokens": reference,
        "saved_tokens": saved,
        "saved_percent": 100 * saved / reference if reference else None,
    }


def benchmark(source, temp, args, env, encoding, rng):
    examples, name = source.parent, source.stem
    baseline = examples / f"{name}.py"
    compiled = temp / f"{name}.py"
    helpers = examples / f"{name}.helper.py"
    expected = (examples / f"{name}.out").read_bytes()
    input_path = examples / f"{name}.in"
    if not input_path.exists():
        input_path = Path(os.devnull)

    compiler = [sys.executable, "-m", "agentlang"]
    subprocess.run([*compiler, "compile", str(source), "-o", str(compiled)],
                   cwd=examples, env=env, check=True, stdout=subprocess.DEVNULL)
    # All paths are absolute since each workload runs in the examples directory.
    commands = {
        "python": [sys.executable, str(baseline)],
        "compile_run": [*compiler, "run", str(source)],
        "cached_python": [sys.executable, str(compiled)],
    }
    sources = {"python": baseline, "compile_run": source, "cached_python": compiled}
    if helpers.is_file():
        expanded_helpers = temp / helpers.name
        subprocess.run([*compiler, "compile", str(helpers), "-o", str(expanded_helpers)],
                       cwd=examples, env=env, check=True, stdout=subprocess.DEVNULL)
        commands["python_helpers"] = [sys.executable, str(expanded_helpers)]
        sources["python_helpers"] = helpers

    stats = {mode: file_stats(path, encoding) for mode, path in sources.items()}
    samples = {mode: [] for mode in commands}
    for order in orders(commands, args.warmups, rng):
        for mode in order:
            trial(commands[mode], examples, env, input_path, expected)
    for round_number, order in enumerate(orders(commands, args.runs, rng), 1):
        for position, mode in enumerate(order, 1):
            measurement = trial(commands[mode], examples, env, input_path, expected)
            samples[mode].append({"round": round_number, "position": position, **measurement})
    result = {
        "source": stats, "expected_stdout_sha256": hashlib.sha256(expected).hexdigest(),
        "token_comparisons": {
            ref: token_comparison(stats["compile_run"]["tokens"], stats[ref]["tokens"])
            for ref in ("python", "python_helpers") if ref in stats
        },
        "samples": samples, "summary": {mode: describe(rows) for mode, rows in samples.items()},
    }
    for mode, metrics in result["summary"].items():
        wall, cpu, rss = (metrics[key] for key in ("wall_ms", "cpu_ms", "peak_rss_mib"))
        print(f"{name:<22} {mode:<15} {stats[mode]['tokens']:>7} {wall['median']:>9.2f} "
              f"{wall['p25']:>7.2f}–{wall['p75']:<7.2f} {cpu['median']:>9.2f} {rss['median']:>9.2f}")
    return result


def main():
    args = arguments()
    try:
        import tiktoken
    except ImportError:
        raise SystemExit("Install tiktoken in the Python environment used to run this benchmark.") from None
    encoding = tiktoken.get_encoding("o200k_base")
    examples = args.examples.resolve()
    paths = {path.stem: path for path in sorted(examples.glob("*.ag"))}
    names = list(dict.fromkeys(args.case)) if args.case else list(paths)
    if not names or set(names) - paths.keys():
        raise SystemExit(f"No matching cases. Available in {examples}: {', '.join(paths) or '(none)'}")
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    rng = random.Random(args.seed)
    report = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(), "machine": platform.machine(),
            "processor": cpu_model(), "logical_cpus": os.cpu_count(),
            "python": sys.version, "executable": Path(sys.executable).name,
            "tiktoken": importlib.metadata.version("tiktoken"), "encoding": encoding.name,
        },
        "config": {"runs": args.runs, "warmups": args.warmups, "seed": args.seed,
                   "scale_factor": args.scale, "PYTHONHASHSEED": 0},
        "implementation_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in (ROOT / "agentlang", HERE) for path in sorted(folder.glob("*.py"))
        },
        "method": {
            "source": "Entire UTF-8 files including comments and final newline, without Markdown fences.",
            "wall_ms": "Elapsed spawn through exit of a fresh process, including interpreter startup.",
            "cpu_ms": "OS wait4 user plus system CPU time.",
            "peak_rss_mib": "OS wait4 per-process maximum resident set size in MiB.",
            "compile_run": "Translate and execute the source on every invocation. OS caches may be warm.",
            "cached_python": "Compile once before timing, then invoke the generated Python as a script.",
            "python_helpers": "Python syntax with the compact language's implicit helpers. Count the authored "
                              ".helper.py, expand its prelude before timing, then execute the expanded script.",
            "order": "Modes interleaved within each round, rotated and shuffled in seeded blocks.",
            "scale_factor": "Each full seed sequence is repeated in order. CSV keeps one header. "
                            "Goldens preserve group means and most frequent word, multiply counts, "
                            "and repeat each stable score tie group in order.",
            "correctness": "Every warmup and measured run must match the expected stdout bytes and exit zero.",
        },
        "cases": {},
    }
    print(f"{'case':<22} {'mode':<15} {'tokens':>7} {'wall ms':>9} {'wall IQR (ms)':>15} "
          f"{'CPU ms':>9} {'RSS MiB':>9}")
    with tempfile.TemporaryDirectory(prefix="agentlang-bench-") as directory:
        temp = Path(directory)
        working, dimensions = prepare_examples(examples, temp / "examples", args.scale, names)
        # Support imports in both the temp directory and the workload's normal working directory.
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), str(working), env.get("PYTHONPATH")]))
        for name in names:
            case = benchmark(working / paths[name].name, temp, args, env, encoding, rng)
            case["workload"] = dimensions.get(name, {})
            report["cases"][name] = case
    report["token_totals"] = {}
    for ref in ("python", "python_helpers"):
        matched = [row["token_comparisons"][ref] for row in report["cases"].values()
                   if ref in row["token_comparisons"]]
        if matched:
            totals = token_comparison(sum(row["compact_tokens"] for row in matched),
                                      sum(row["reference_tokens"] for row in matched))
            report["token_totals"][ref] = {"cases": len(matched), **totals}
            pct = totals["saved_percent"]
            if pct is not None:
                print(f"Compact vs {ref} ({len(matched)} cases): {totals['compact_tokens']} vs "
                      f"{totals['reference_tokens']} source tokens, {pct:.1f}% saved.")
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(names)} cases. Median values shown. Full samples: {args.output}")


if __name__ == "__main__":
    main()
