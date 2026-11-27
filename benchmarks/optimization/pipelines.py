"""Differential workloads and CPU timings for compiled collection pipelines."""

import argparse
from collections import Counter
from contextlib import redirect_stdout
from io import StringIO
import json
from operator import itemgetter, methodcaller
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns, process_time_ns
from unittest.mock import patch

from agentlang import compiler
from benchmarks.optimization.baseline import REVISION, load_compiler
from benchmarks.pilot.runtime.scale import prepare_examples

ROOT = Path(__file__).resolve().parents[2]
SEED = 170314
# Each suffix is a separate AgentLang function, compiled in both releases.
PROGRAMS = {
    "records": (
        ":s _$score", ":k _$score", ":x _$score", ":t limit, _$score",
        ":s _?score", ":s -_$score", ":s (_$score, _$id)", ":t limit, (_$score, _$id)",
        ":s _$score:l", ":s _$score:n", ":t limit, _$score:l", ":t limit, _$score:n",
    ),
    "pairs": (
        ":s _[1]", ":k _[1]", ":x _[1]", ":t limit, _[1]",
        ":s _[-1]", ":s _[len(_) - 1]", ":s _:l", ":t limit, _:n",
    ),
    "numbers": (
        ":s _", ":k _", ":x _", ":t limit, _", ":s:l:n", ":l:n",
        ":l:l", ":c limit:l", ":c limit:n", ":w _ > 0:n", ":m _ * 3:w _ < 30:l", ":n",
    ),
}


def compile_functions(module):
    result = {}
    for kind, suffixes in PROGRAMS.items():
        for suffix in suffixes:
            text = f"def run(rows, limit):\n    return rows{suffix}\n"
            code, env = module.prepare_run(text, "<pipeline>")
            exec(code, env)
            result[kind, suffix] = env["run"]
    return result


def outcome(function, rows, mode, limit):
    # Create a fresh input for each arm, particularly for one-shot inputs.
    if mode == 1:
        rows = tuple(rows)
    elif mode == 2:
        rows = iter(rows)
    elif mode == 3:
        rows = (item for item in rows)
    try:
        result = function(rows, limit)
    except (KeyError, ValueError, TypeError) as exc:
        return type(exc), exc.args
    return type(result), result


def differential(before, after, cases):
    old = compile_functions(before)
    new = compile_functions(after)
    rng = random.Random(SEED)
    errors = Counter()
    evaluations = 0
    for index in range(cases):
        size = rng.randrange(19)
        values = [rng.randrange(-20, 21) for _ in range(size)]
        order = index % 4
        if order < 2:
            values.sort(reverse=bool(order))
        elif order == 2 and size:
            values = [values[0]] * size
        pairs = [(index * 20 + i, value) for i, value in enumerate(values)]
        records = [{"id": i, "score": value} for i, value in pairs]
        if index % 23 == 0 and records:
            del records[rng.randrange(size)]["score"]
        inputs = {"numbers": values, "pairs": pairs, "records": records}
        limit = rng.randrange(size + 4)
        mode = rng.randrange(4)
        for (kind, suffix), ref in old.items():
            rows = inputs[kind]
            expected = outcome(ref, rows, mode, limit)
            actual = outcome(new[kind, suffix], rows, mode, limit)
            if actual != expected:
                raise AssertionError((index, kind, suffix, expected, actual))
            evaluations += 1
            if issubclass(actual[0], Exception):
                errors[actual[0].__name__] += 1
    return {"input_draws": cases, "compiled_program_pairs": len(old),
            "matched_program_input_pairs": evaluations, "executions_per_pair": 2,
            "matching_exceptions": dict(errors)}


def measure(functions, iterations, rng):
    cpu = {k: [] for k in functions}
    wall = {k: [] for k in functions}
    keys = list(functions)
    for rep in range(12):
        rng.shuffle(keys)
        for key in keys:
            run = functions[key]
            start = perf_counter_ns()
            cpu_start = process_time_ns()
            for _ in range(iterations):
                run()
            cpu_ns = process_time_ns() - cpu_start
            wall_ns = perf_counter_ns() - start
            if rep:
                cpu[key].append(round(cpu_ns / iterations, 1))
                wall[key].append(round(wall_ns / iterations, 1))
    return {"iterations": iterations, "measured_rounds": 11,
            "median_cpu_ns": {k: median(v) for k, v in cpu.items()},
            "median_wall_ns": {k: median(v) for k, v in wall.items()}}


def timing_matrix(before, after, rng):
    old = compile_functions(before)
    new = compile_functions(after)
    result = []
    for size in (1, 32, 2048):
        values = [rng.randrange(-size, size + 1) for _ in range(size)]
        pairs = list(enumerate(values))
        inputs = {"numbers": values, "pairs": pairs, "records": [dict(id=i, score=v) for i, v in pairs]}
        for kind, suffix in (("records", ":s _$score"), ("records", ":k _$score"),
                             ("records", ":x _$score"), ("records", ":t limit, _$score"),
                             ("records", ":s (_$score, _$id)"),
                             ("pairs", ":s _[1]"), ("numbers", ":s _"), ("numbers", ":l:n"),
                             ("numbers", ":l:l"), ("numbers", ":s:l:n"), ("numbers", ":c limit:n")):
            rows = inputs[kind]
            functions = {k: lambda f=m[kind, suffix]: f(rows, 6) for k, m in (("old", old), ("new", new))}
            result.append({"size": size, "kind": kind, "pipeline": suffix,
                           **measure(functions, max(8, 4096 // size), rng)})
        # Alternative callbacks and simplifications on the same fixture.
        records = inputs["records"]
        alternatives = {
            "required_lambda": lambda: sorted(records, key=lambda r: r["score"]),
            "itemgetter": lambda: sorted(records, key=itemgetter("score")),
            "optional_lambda": lambda: sorted(records, key=lambda r: r.get("score")),
            "methodcaller": lambda: sorted(records, key=methodcaller("get", "score")),
            "multi_lambda": lambda: sorted(records, key=lambda r: (r["score"], r["id"])),
            "multi_itemgetter": lambda: sorted(records, key=itemgetter("score", "id")),
        }
        result.append({"size": size, "kind": "candidate_keys",
                       **measure(alternatives, max(8, 4096 // size), rng)})
    return result


def scripts(before, after, rng, temp):
    script = ROOT / "examples/sort_scores.ag"
    source = script.read_text()
    result = []
    for scale in (1, 32, 2048):
        base, _ = prepare_examples(ROOT / "examples", temp / str(scale), scale, ["sort_scores"])
        data = (base / "sort_scores.in").read_text()
        expected = json.loads((base / "sort_scores.out").read_bytes())
        functions = {}
        for arm, module in (("old", before), ("new", after)):
            code, bindings = module.prepare_run(source, str(script))

            def run(code=code, bindings=bindings):
                output = StringIO()
                with patch.object(sys, "stdin", StringIO(data)), redirect_stdout(output):
                    exec(code, bindings.copy())
                return output.getvalue()

            if json.loads(run()) != expected:
                raise AssertionError((script, scale, arm))
            functions[arm] = run
        result.append({"path": str(script.relative_to(ROOT)), "records": 6 * scale,
                       **measure(functions, max(1, 128 // scale), rng)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=int, default=65536)
    parser.add_argument("--checks-only", action="store_true",
                        help="run the differential checks without collecting timings")
    parser.add_argument("--also-check", action="append", type=Path, default=[], metavar="PYTHON",
                        help="replay the same inputs with another Python interpreter")
    args = parser.parse_args()
    if args.inputs < 1:
        parser.error("--inputs must be positive")
    rng = random.Random(SEED + 1)
    with TemporaryDirectory() as directory:
        temp = Path(directory)
        old = load_compiler(temp / "previous")
        # Standalone, prepared, and before/after share emitted stage expressions.
        result = {"baseline": REVISION, "python": platform.python_version(), "platform": platform.platform(),
                  "seed": SEED, "programs": PROGRAMS, "simulation": differential(old, compiler, args.inputs)}
        if not args.checks_only:
            result["timing"] = timing_matrix(old, compiler, rng)
            result["prepared_scripts"] = scripts(old, compiler, rng, temp)
        if args.also_check:
            result["other_interpreters"] = []
            for executable in args.also_check:
                command = [executable, "-m", "benchmarks.optimization.pipelines",
                           "--inputs", str(args.inputs), "--checks-only"]
                replay = json.loads(subprocess.check_output(command, cwd=ROOT))
                result["other_interpreters"].append({"python": replay["python"], "simulation": replay["simulation"]})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
