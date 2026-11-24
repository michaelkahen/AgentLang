import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentlang import compile_source


ROOT = Path(__file__).resolve().parents[1]


def output(source):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        exec(compile_source(source), {})
    return stream.getvalue()


class PipelineTests(unittest.TestCase):
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
