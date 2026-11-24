import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentlang import compile_python, compile_source, count_short_stages


ROOT = Path(__file__).resolve().parents[1]


def output(source):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        exec(compile_source(source), {})
    return stream.getvalue()


class PipelineTests(unittest.TestCase):
    def test_fstring_text_does_not_change_pipeline_parsing(self):
        source = '''n = 2
first = f"={n}":n
second = f"lambda{n}":n
third = f"{n}:":n
j [first, second, third]
'''
        self.assertEqual(output(source), "[2, 7, 2]\n")
        self.assertEqual(count_short_stages(source), 3)

    def test_record_fields_in_python_expressions(self):
        source = '''
rows = [{"crew": {"id": 2}}, {"crew": {"id": 1}}]
ids = [row$crew$id for row in rows]
label = "$crew d{ids}"  # d{label} and invalid $ are literal here
j d{ids, label}
'''
        self.assertEqual(output(source), '{"ids": [2, 1], "label": "$crew d{ids}"}\n')
        self.assertEqual(output('v={"class":0}\nv$class += 1\np v$class'), "1\n")
        with self.assertRaises(SyntaxError):
            compile_python('x = row$field')
        for bad in ['x = $missing', 'x = row$2', 'x = row$ key', 'x = d{a + b}']:
            with self.subTest(bad=bad), self.assertRaises(SyntaxError):
                compile_source(bad)

    def test_rankings_keep_ties_and_evaluate_count(self):
        source = '''
rows = [{"score":2,"id":1},{"score":1,"id":2},{"score":1,"id":3}]
n = 1
subset = rows:t n + 1, _$score
best = rows:k _$score
last = rows:x _$score
j [subset, best$id, last$id]
'''
        self.assertEqual(output(source), '[[{"score": 1, "id": 2}, {"score": 1, "id": 3}], 2, 1]\n')
        self.assertEqual(output("p []:t 0"), "[]\n")
        with self.assertRaises(ValueError):
            output("p [1]:t -1")
        with self.assertRaises(ValueError):
            output("p []:k")

    def test_structured_value_bytes_and_hash_in_both_front_ends(self):
        import hashlib
        source = '''values = [v("true"), v("{'x': 2}"), v('bogus', 'fallback')]
digest = h(b(values))
wj([values, digest, t([4,1,1,2],2), k([3,1]), x([3,1])])
'''
        import json
        values = [True, {"x": 2}, "fallback"]
        digest = hashlib.sha256((json.dumps(values) + "\n").encode()).hexdigest()
        for build in (compile_python, compile_source):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                exec(build(source), {})
            self.assertEqual(json.loads(buf.getvalue()), [values, digest, [1, 1], 1, 3])
        self.assertEqual(output('f = h\np f(b(1))'), hashlib.sha256(b"1\n").hexdigest() + "\n")

    def test_in_memory_and_standalone_use_same_bindings(self):
        from agentlang.compiler import prepare_run
        source = '''"docstring"
from __future__ import annotations
items = [{"s":1}, {"s":2}, {"s":3}]
first = items:t 2, -_$s
score = first:a _$s
common = [3,3,2]:c 1
j d{first,score,common}
'''
        program, namespace = prepare_run(source, "demo.ag")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(program, namespace)
        self.assertEqual(buf.getvalue(), output(source))
        self.assertEqual(namespace["__doc__"], "docstring")

    def test_helper_insertion_and_builtin_shadowing(self):
        from agentlang.compiler import prepare_run
        source = '''"données"; from __future__ import annotations; print(v("true"))
ValueError = TypeError = RecursionError = None
print(v("not valid","fallback"))
'''
        self.assertEqual(output(source), "True\nfallback\n")
        code, env = prepare_run(source, "demo.ag")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exec(code, env)
        self.assertEqual(stream.getvalue(), output(source))
        self.assertEqual(env["__doc__"], "données")

    def test_fused_stages(self):
        source = 'p ["ab","ac"]:f _:w _ != "c":c 1:h'
        self.assertEqual(output(source), "('a', 2)\n")
        self.assertEqual(count_short_stages(source), 4)
        self.assertEqual(output("j [3,1,2]:m _*2:s:l"), "[2, 4, 6]\n")
        self.assertEqual(output("p [1,2,3]:a"), "2\n")
        self.assertEqual(output("p [1,2,3]:u"), "6\n")
        self.assertEqual(output('p ["a:n","b"]:where _.endswith(":n"):n'), "1\n")

    def test_abbreviations_preserve_python_bindings(self):
        source = 's = {1}\nj = 0\nj += 1\np = [j]\np[0] = 4\nx: int = p[0]\nresult = {2} | s\n'
        self.assertEqual(compile_source(source), source)
        self.assertEqual(count_short_stages('x = ":n"  # :c 1\n' + source), 0)
        self.assertEqual(output('def classify(a):\n    return a:m _[1:]:l\nj classify(["pa"])'), '["a"]\n')

    def test_local_callback_names_do_not_install_global_helpers(self):
        from agentlang.compiler import prepare_run
        source = '''def apply(x, shahex):
    return x(shahex(3))

assert apply(str, lambda v: v + 1) == "4"
assert {"x", "greatest", "shahex"}.isdisjoint(globals())
'''
        for build in (compile_source, compile_python):
            self.assertEqual(build(source), source)
            exec(build(source), {})
        code, namespace = prepare_run(source, "callbacks.ag")
        exec(code, namespace)

    def test_short_helper_calls_in_both_languages(self):
        for build in (compile_source, compile_python):
            source = 'wj(sorted(r()))'
            completed = subprocess.run([sys.executable, "-I", "-c", build(source)],
                                       input=b"[3, 1]", capture_output=True, check=True)
            self.assertEqual(completed.stdout, b"[1, 3]\n")
            source = "xs = [r for r in range(4)]\n"
            self.assertEqual(build(source), source)

    def test_native_control_preserves_python(self):
        source = 'count = {2}\nresult = {1} | count\n'
        self.assertEqual(compile_python(source), source)
        with self.assertRaises(SyntaxError):
            compile_python("emit readjson() | first")

    def test_both_front_ends_embed_shared_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_file = Path(directory) / "items.csv"
            csv_file.write_bytes(b'name,value\r\n"hello, world",3\r\n')
            source = f'writejson(csvrows({str(csv_file)!r}))'
            expected = '[{"name": "hello, world", "value": "3"}]\n'
            for build in (compile_python, compile_source):
                generated = build(source)
                self.assertNotIn("def readjson", generated)
                proc = subprocess.run([sys.executable, "-I", "-c", generated], cwd=directory,
                                      text=True, capture_output=True, check=True)
                self.assertEqual(proc.stdout, expected)

    def test_stages(self):
        self.assertEqual(output("emit [1, 2, 3] | where _ % 2 | map _ * 2 | sum"), "8\n")
        self.assertEqual(output("emit [1, 2, 3] | sum _ * 2"), "12\n")
        self.assertEqual(output("emit [1, 2, 3] | mean"), "2\n")
        self.assertEqual(output("emit ['ab', 'ca'] | flat _ | common 1 | first"), "('a', 2)\n")
        self.assertEqual(output("jsonout [4, 1] | sort | list"), "[1, 4]\n")
        self.assertEqual(output("emit [] | count"), "0\n")

    def test_lazy_map_and_where(self):
        source = """
def values():
    yield 2
    raise AssertionError("evaluated past the first match")
emit values() | map _ * 3 | where _ > 4 | first
"""
        self.assertEqual(output(source), "6\n")

    def test_nesting_strings_and_comments(self):
        source = """
def count(values):
    return values | where _.get("a|b", 0) == (1 | 2) | count  # ignored | first
emit count([{"a|b": 3}])
"""
        self.assertEqual(output(source), "1\n")

    def test_plain_python_and_annotations(self):
        source = 'def f(arg: int | list) -> int | list:\n    return arg\nx: int | list = f(3)\n'
        self.assertEqual(compile_source(source), source)
        self.assertEqual(output('x = ({"a": 1} | {"b": 2}); emit len(x)'), "2\n")

    def test_globals_shadow_builtins(self):
        self.assertEqual(output("sum = print = None\nemit [2, 4] | count"), "2\n")

    def test_method_and_future_import(self):
        source = '''"agent module"
from __future__ import annotations
class Sample:
    def run(self):
        return [1, 2, 3] | mean
emit Sample().run()
'''
        self.assertEqual(output(source), "2\n")
        self.assertTrue(compile_source(source).startswith('"agent module"\nfrom __future__'))

    def test_stage_diagnostics(self):
        for source in ["emit [1] | map", "emit [1] | count 1", "emit [1] | map _ | missing", "emit [1] | first |"]:
            with self.subTest(source=source), self.assertRaises(SyntaxError):
                compile_source(source)

    def test_examples_run_and_compile_standalone(self):
        examples = ROOT / "examples"
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        with tempfile.TemporaryDirectory() as directory:
            for source in sorted(examples.glob("*.ag")):
                with self.subTest(source=source.name):
                    target = Path(directory) / (source.stem + ".py")
                    stdin = source.with_suffix(".in")
                    data = stdin.read_bytes() if stdin.exists() else b""
                    cli = [sys.executable, "-m", "agentlang"]
                    subprocess.run([*cli, "compile", source, "-o", target], cwd=examples, env=env, check=True)
                    for command in [[*cli, "run", source], [sys.executable, "-I", target]]:
                        result = subprocess.run(command, cwd=examples, env=env, input=data, capture_output=True, check=True)
                        self.assertEqual(result.stdout, source.with_suffix(".out").read_bytes())


if __name__ == "__main__":
    unittest.main()
