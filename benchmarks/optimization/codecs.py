"""Compare JSON/literal parsing and JSON byte encoding on existing scripts."""

import ast
from collections import Counter
from contextlib import redirect_stdout
import inspect
from io import StringIO
import json
import os
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns
from unittest.mock import patch

from agentlang import compiler
from benchmarks.long.workloads.cases import matches, prepare
from benchmarks.optimization.baseline import load_compiler, REVISION
from benchmarks.optimization.pipelines import measure

ROOT = Path(__file__).resolve().parents[2]
SEED = 161822


def alternatives(old):
    # Make just the indicated substitutions in the pinned helper definition so
    # Python-level wrappers cannot bias a sub-microsecond codec comparison.
    before = inspect.getsource(old)
    deferred = before.replace("    import ast\n", "").replace(
        "    try:\n        return ast.literal_eval", "    import ast\n    try:\n        return ast.literal_eval")
    start = deferred.index("    try:\n        return json.loads")
    end = deferred.index("    if not _ag_builtins.isinstance")
    guarded = deferred[:start] + """    if _ag_builtins.type(text) is not _ag_builtins.str or "'" not in text or '"' in text:
""" + "".join("    " + s for s in deferred[start:end].splitlines(keepends=True)) + deferred[end:]
    functions = {"previous": old}
    for name, source in (("defer_ast", deferred), ("skip_impossible_json", guarded)):
        env = old.__globals__.copy()
        exec(source, env)
        functions[name] = env["parsevalue"]
    return functions


def encode_first(value):
    import json

    return json.dumps(value).encode("utf-8") + b"\n"


def standalone_imports(module):
    program = module.compile_source("""import sys
states = ['ast' in sys.modules]
assert v('true') is True
states.append('ast' in sys.modules)
assert v("('a', 2)") == ('a', 2)
states.append('ast' in sys.modules)
wj(states)
""")
    out = subprocess.check_output([sys.executable, "-I", "-S", "-c", program])
    return dict(zip(("before", "after_json", "after_literal"), json.loads(out)))


def fresh_json(old, directory):
    # Run a complete emitted program in a fresh interpreter for each sample.
    # This captures loading ast on the previous JSON-only path.
    rng = random.Random(SEED)
    arms = {"previous": old, "shipped": compiler}
    commands = {}
    for name, module in arms.items():
        path = directory / f"{name}.py"
        path.write_text(module.compile_source("wj(v('true'))"), encoding="utf-8")
        commands[name] = [sys.executable, "-I", str(path)]
    samples = {k: [] for k in arms}
    names = list(arms)
    for i in range(22):
        if i % 2 == 0:
            rng.shuffle(names)
        else:
            names.reverse()
        for name in names:
            start = perf_counter_ns()
            output = subprocess.check_output(commands[name])
            elapsed_ms = (perf_counter_ns() - start) / 1e6
            if json.loads(output) is not True:
                raise AssertionError(output)
            if i >= 2:
                samples[name].append(round(elapsed_ms, 3))
    return {"program": "wj(v('true'))", "wall_ms": samples,
            "median_wall_ms": {k: median(v) for k, v in samples.items()}}


def distribution(value):
    try:
        json.loads(value)
        return "json"
    except (TypeError, ValueError, RecursionError):
        pass
    try:
        ast.literal_eval(value.strip())
        return "literal"
    except (TypeError, ValueError, SyntaxError, AttributeError, RecursionError):
        return "default"


def check(parse, encode):
    class Text(str):
        def __contains__(self, needle):
            raise AssertionError("called a subclass hook")
    marker = object()
    rng = random.Random(SEED)
    atoms = [None, True, 32, -2.5, "'", '"', "雪", "O'Brien", "\ud800", "NaN", "\x00"]
    inputs = [1, b"", bytearray(b"\xff"), Text('{"a":1}'), Text("{'a':2}"), None, [], " \ufeff {}"]
    encodings = 0
    for _ in range(1024):
        data = {str(rng.randrange(13)): rng.choices(atoms, k=rng.randrange(10)) for _ in range(rng.randrange(6))}
        strict = json.dumps(data)
        inputs.extend([strict, strict.encode(), bytearray(strict.encode()), repr(data), strict[:-1]])
        expected = encode["previous"](data)
        if any(f(data) != expected for f in encode.values()):
            raise AssertionError(data)
        encodings += 1
    for value in inputs:
        expected = parse["previous"](value, marker)
        for name, f in parse.items():
            actual = f(value, marker)
            if type(actual) is not type(expected) or repr(actual) != repr(expected):
                raise AssertionError((name, value, expected, actual))
    return {"parse_inputs": len(inputs), "encode_inputs": encodings}


def script(task, variant, methods, directory, rng):
    source = ROOT / f"benchmarks/patterns/generation/observations/sources/{task}-compact-r1-a1.ag"
    code, env = compiler.prepare_run(source.read_text(), str(source))
    fixture = prepare(task, variant, directory)
    if task == "movie_credits":
        binding = "v"
    else:
        binding = "b"

    def run(f):
        namespace = dict(env, **{binding: f})
        out = StringIO()
        with patch.object(sys, "stdin", StringIO(fixture["stdin"].decode())), redirect_stdout(out):
            exec(code, namespace)
        return out.getvalue()

    categories = Counter()

    def counted(value):
        if binding == "v":
            categories[distribution(value)] += 1
        else:
            categories["json_values"] += 1
        return methods["previous"](value)

    previous = Path.cwd()
    try:
        os.chdir(directory)
        if not matches(run(counted), fixture["expected"]):
            raise AssertionError((task, variant))
        calls = {}
        for label, method in methods.items():
            if not matches(run(method), fixture["expected"]):
                raise AssertionError((task, variant, label))
            calls[label] = lambda f=method: run(f)
        result = measure(calls, 16 if variant == "audit" else 1, rng)
    finally:
        os.chdir(previous)
    return {"source": str(source.relative_to(ROOT)), "fixture": variant, "calls": categories, **result}


def main():
    rng = random.Random(SEED)
    with TemporaryDirectory() as name:
        temp = Path(name)
        old = load_compiler(temp / "previous")
        parse = alternatives(old.SHARED_HELPERS["v"])
        encode = {"previous": old.SHARED_HELPERS["b"], "encode_then_append": encode_first}
        report = {"python": platform.python_version(), "platform": platform.platform(),
                  "baseline": REVISION, "seed": SEED, "equivalence": check(parse, encode)}
        report["standalone_ast_loaded"] = {"previous": standalone_imports(old),
                                           "shipped": standalone_imports(compiler)}
        report["fresh_json_only"] = fresh_json(old, temp)
        values = {
            "json": ('[{"id":1},{"name":"Sci-Fi"}]', "false", "3", '''{"x":"O'Brien"}'''),
            "python": ("[{'id': 1}, {'id': 2}]", "{'key': '雪'}", "{'title': \"O'Brien\"}"),
            "invalid": ("malformed", "[1,", "{nope}", b"bad json", None),
        }
        probes = []
        for group, items in values.items():
            calls = {k: (lambda f=f, items=items: [f(v) for v in items]) for k, f in parse.items()}
            probes.append({"codec": "parse", "inputs": group, **measure(calls, 256, rng)})
        for size in (1, 128, 8192):
            value = [[i, "René", i % 5] for i in range(size)]
            calls = {k: (lambda f=f: f(value)) for k, f in encode.items()}
            probes.append({"codec": "bytes", "rows": size, **measure(calls, max(2, 2048 // size), rng)})
        report["probes"] = probes
        report["scripts"] = [script(task, variant, methods, temp / (task + variant), rng)
                             for task, methods in (("movie_credits", parse), ("fixture_pack", encode))
                             for variant in ("audit", "profile")]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
