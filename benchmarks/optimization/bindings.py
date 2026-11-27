"""Compare helper resolution strategies with the same previous-release translator."""

import argparse
import ast
import json
from pathlib import Path
import platform
import random
import re
import statistics
import tempfile
import time
from unittest.mock import patch

from agentlang import compiler
from benchmarks.optimization.baseline import REVISION, load_compiler, scripts
from benchmarks.scripting.simulation_archive import sources as archive_sources, tooling_sources

ROOT = Path(__file__).resolve().parents[2]


def helper_free_probe(programs, old, rounds, rng):
    """Try bypassing AST binding discovery entirely for plainly helper-free text."""
    markers = re.compile(r"\b(?:_ag_\w*|" + "|".join(compiler.SHARED_HELPERS) + r")\b", re.ASCII)
    times = {"ordinary": 0, "guard": 0}
    seen = set()
    eligible = 0
    for path, source, _ in programs:
        if source in seen:
            continue
        seen.add(source)
        output, _ = old._translate(source, path)
        skip = output.isascii() and not markers.search(output)
        if skip:
            eligible += 1
            names, aliases, shared = compiler._bindings(ast.parse(output), output, path, True)
            if aliases or shared or any(name.startswith("_ag_") for name in names):
                raise AssertionError(path)
        samples = {k: [] for k in times}
        for i in range(rounds + 2):
            order = list(times)
            rng.shuffle(order)
            for method in order:
                start = time.process_time_ns()
                if method == "guard" and output.isascii() and not markers.search(output):
                    code = compile(output, path, "exec")
                else:
                    tree = ast.parse(output, path)
                    compiler._bindings(tree, output, path, True)
                    code = compile(tree, path, "exec")
                elapsed = time.process_time_ns() - start
                del code
                if i >= 2:
                    samples[method].append(elapsed)
        for method, ns in samples.items():
            times[method] += statistics.median(ns)
    return {"sources": len(seen), "eligible": eligible, "sum_of_median_cpu_us": {
        k: round(v / 1000, 3) for k, v in times.items()
    }}


def pruned_stdlib_walk(tree):
    """Keep the two work lists but leave child discovery to the standard library."""
    names, direct, nested = set(), set(), []
    for top_level, pending in ((True, [tree]), (False, nested)):
        while pending:
            node = pending.pop()
            if isinstance(node, ast.Name):
                names.add(node.id)
                continue
            if not node._fields or isinstance(node, ast.Constant):
                continue
            if top_level and isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                direct.add(node.func.id)
            children = nested if top_level and isinstance(node, compiler._NESTED_SCOPES) else pending
            children.extend(ast.iter_child_nodes(node))
    return names, direct


def run(rounds):
    rng = random.Random(31091)
    with tempfile.TemporaryDirectory() as tmp:
        old = load_compiler(Path(tmp))
        previous_bindings = old._bindings
        current_walk = compiler._binding_names
        rows = []
        for filename, source in scripts():
            output, _ = old._translate(source, filename)
            tree = ast.parse(output)
            expected = previous_bindings(tree, output, filename, True)
            samples = {key: [] for key in ("old", "stdlib", "fields")}
            for i in range(rounds + 2):
                order = list(samples)
                rng.shuffle(order)
                for name in order:
                    resolver = previous_bindings if name == "old" else compiler._bindings
                    walker = pruned_stdlib_walk if name == "stdlib" else current_walk
                    with patch.object(compiler, "_binding_names", walker), patch.object(old, "_bindings", resolver):
                        if i == 0 and resolver(tree, output, filename, True) != expected:
                            raise AssertionError((filename, name))
                        start = time.process_time_ns()
                        artifact = old.prepare_run(source, filename)
                        elapsed = time.process_time_ns() - start
                        del artifact
                        if i >= 2:
                            samples[name].append(elapsed)
            rows.append({"source": filename, "median_cpu_us": {
                key: round(statistics.median(values) / 1000, 3) for key, values in samples.items()
            }})
        guard = {k: helper_free_probe(corpus(ROOT), old, rounds, rng)
                 for k, corpus in (("archive", archive_sources), ("tooling", tooling_sources))}
    sums = {key: round(sum(row["median_cpu_us"][key] for row in rows), 3) for key in samples}
    return {"baseline": REVISION, "python": platform.python_version(), "platform": platform.platform(),
            "seed": 31091, "measured_rounds": rounds, "warmups": 2,
            "sum_of_source_cpu_medians_us": sums, "sources": rows, "helper_free_probe": guard}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=31)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    print(json.dumps(run(args.rounds), indent=2))
