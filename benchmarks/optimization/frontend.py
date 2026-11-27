"""Compare preparation with the previous tokenizer and with field-aware scan routing."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from agentlang import compiler
from benchmarks.optimization.baseline import REVISION, load_compiler
from benchmarks.scripting.record_preparation import changed_programs, run as compare_spellings
from benchmarks.scripting.simulation_archive import sources, tooling_sources

ROOT = Path(__file__).resolve().parents[2]
SEED = 409157


def lexical_cases():
    """Cross field positions, statement boundaries and literal/comment contexts."""
    expressions = (
        "row", "row$id", "row?key", "row$if?yes", "table[2]?match", "d{left,right=3}",
        "d{nested=d{v=row?value}}", "d{f=lambda x,y: (x,y)}", "row$键",
        "{'x': sum(items)}", "f'{row!r}:s'", "row ?flag", "$missing", "d{v,,q}",
        "row? key", "d{x=}", "d{x=v for v in a}", "(row$nested?key)",
    )
    contexts = (
        "# j bogus:s\n", "prefix = 'p row?value:m'\n", "prefix = {'x': sum([1])}\n",
        "prefix = '''p row\ntext?:k\n'''\n", "prefix = '\\n':n\n", "prefix = row?flag\n",
        "left = 2; right = 7 # | map\n", "dotted = 'é':h\r\n", "prefix = d{left}\n",
    )
    forms = (
        "out = {}", "p {}", "j {}", "emit {}", "j {}:s", "out = {}:m _:l",
        "out = {} | first", "out = {}:\\\n  n", "p {}:s:", "out = {}:m _ | missing",
        "if True:\n\tp {}", "def fn():\n    return {}:n", "x = 1; p {}:s",
        "out = (\n    {}\n):n", "out = [v for v in {}]", "out = lambda v: {}",
        "out = x[{}:n]", "out = dict(key={})", "out = f'text, {{{}!r}}'",
        "out = ({}\n", "if {}:\n    pass",
    )
    for prefix in contexts:
        for expr in expressions:
            for form in forms:
                yield prefix + form.format(expr) + "\n"


def translation(parser, source):
    try:
        output, count = parser(source, "probe.ag")
        compile(output, "probe.ag", "exec")
    except SyntaxError as error:
        return "error", type(error).__name__, error.args
    return "ok", output, count


def check(previous):
    counts = {"ok": 0, "error": 0, "changed_record_boundary": 0}
    # Compare the frontend independently of intentional changes in stage lowering.
    with patch.object(previous, "_rewrite", compiler._rewrite):
        for source in lexical_cases():
            expected = translation(previous._translate, source)
            actual = translation(compiler._translate, source)
            # A leading record in an f-string previously became an escaped
            # opening brace. Spacing it explicitly is an independent oracle.
            if actual != expected and sys.version_info >= (3, 12) and "{d{" in source:
                expected = translation(previous._translate, source.replace("{d{", "{ d{"))
                counts["changed_record_boundary"] += 1
            if actual != expected:
                raise AssertionError((source, expected, actual))
            counts[actual[0]] += 1
    return {"python": platform.python_version(), **counts}


def time_program(old, filename, source, rounds, rng):
    # Replacing only the translator holds the new helper-binding backend fixed.
    current_translate = compiler._translate
    def always_scan(text, name):
        return current_translate(text, name, force_scan=True)

    samples = {name: {"cpu": [], "wall": []}
               for name in ("previous_release", "always_scan", "previous_frontend", "current")}
    for i in range(rounds + 2):
        order = list(samples)
        rng.shuffle(order)
        for name in order:
            mod = old if name == "previous_release" else compiler
            if name == "always_scan":
                translator = always_scan
            elif name == "current":
                translator = current_translate
            else:
                translator = old._translate
            with patch.object(mod, "_translate", translator):
                start = time.perf_counter_ns()
                cpu_start = time.process_time_ns()
                code, namespace = mod.prepare_run(source, filename)
                cpu = time.process_time_ns() - cpu_start
                wall = time.perf_counter_ns() - start
            del code, namespace
            if i >= 2:
                samples[name]["cpu"].append(cpu / 1000)
                samples[name]["wall"].append(wall / 1000)
    return {name: {metric: round(median(series), 3) for metric, series in timings.items()}
            for name, timings in samples.items()}


def cohorts():
    for name, provider in (("archive", sources), ("tooling", tooling_sources)):
        programs = list(changed_programs(provider(ROOT)))
        for index, spelling in ((1, "authored"), (2, "shortened")):
            yield f"{name}_{spelling}", [(p[0], p[index]) for p in programs]
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION, "examples"],
                                    cwd=ROOT, text=True).splitlines()
    yield "examples", [(path, subprocess.check_output(["git", "show", f"{REVISION}:{path}"],
                                                      cwd=ROOT, text=True))
                       for path in paths if path.endswith(".ag")]


def run(old, rounds):
    rng = random.Random(SEED)
    result = {}
    for name, programs in cohorts():
        rng.shuffle(programs)
        rows = []
        for filename, source in programs:
            values = time_program(old, filename, source, rounds, rng)
            rows.append({"source": filename, "sha256": hashlib.sha256(source.encode()).hexdigest(),
                         "median_us": values})
        totals = {arm: {metric: round(sum(row["median_us"][arm][metric] for row in rows), 3)
                        for metric in ("cpu", "wall")} for arm in rows[0]["median_us"]}
        result[name] = {"sum_of_script_medians_us": totals, "programs": rows}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=13)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--also-check", type=Path, action="append", default=[], metavar="PYTHON")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    with tempfile.TemporaryDirectory() as temp:
        old = load_compiler(Path(temp) / "before")
        checks = [check(old)]
        if args.check_only:
            print(json.dumps(checks[0]))
            return
        for executable in args.also_check:
            output = subprocess.check_output([executable, "-m", "benchmarks.optimization.frontend",
                                              "--check-only"], cwd=ROOT)
            checks.append(json.loads(output))
        cohorts_result = run(old, args.rounds)
        paired = compare_spellings(args.rounds)
        print(json.dumps({"baseline": REVISION, "python": platform.python_version(),
                          "platform": platform.platform(), "seed": SEED, "warmup_rounds": 2,
                          "measured_rounds": args.rounds, "lexical_checks": checks,
                          "cohorts": cohorts_result,
                          "paired_spelling_seed": paired["seed"],
                          "current_spelling_comparison": {g: paired[g]["summary"]
                                                          for g in ("archive", "tooling")}}, indent=2))


if __name__ == "__main__":
    main()
