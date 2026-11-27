import unittest

from agentlang import compile_source
from agentlang.compiler import prepare_run


class PipelineLoweringTests(unittest.TestCase):
    def functions(self, expression):
        source = f"def run(rows):\n    return rows{expression}\n"
        namespace = {}
        exec(compile_source(source), namespace)
        yield namespace["run"]
        code, namespace = prepare_run(source, "example.ag")
        exec(code, namespace)
        yield namespace["run"]

    def test_literal_keys_preserve_accesses_and_tie_order(self):
        accesses = []

        class Row(dict):
            def __getitem__(self, key):
                accesses.append((self.get("id"), key))
                return super().__getitem__(key)

        rows = [Row(id=i, score=s) for i, s in enumerate([2, 1, 1])]
        for expression, expected in ((":s _$score", [1, 2, 0]), (":t 2, _$score", [1, 2]),
                                     (":k _$score", 1), (":x _$score", 0)):
            for run in self.functions(expression):
                accesses.clear()
                result = run(iter(rows))
                selected = [r.get("id") for r in result] if isinstance(result, list) else result.get("id")
                self.assertEqual(selected, expected)
                self.assertEqual(accesses, [(0, "score"), (1, "score"), (2, "score")])
                with self.assertRaises(KeyError):
                    run([Row()])
        for run in self.functions(":s (_$score, _$id)"):
            accesses.clear()
            self.assertEqual(run(rows), [rows[1], rows[2], rows[0]])
            self.assertEqual(accesses, [(i, k) for i in range(3) for k in ("score", "id")])

    def test_dynamic_or_optional_keys_keep_python_lookup(self):
        self.assertEqual(next(self.functions(":s _[len(_) - 1]"))([(2, 4), (4, 2)]),
                         [(4, 2), (2, 4)])
        for run in self.functions(":s _?score"):
            self.assertEqual(run([{"score": 2}, {"score": 1}]), [{"score": 1}, {"score": 2}])
        # A one-tuple key differs from its only component. It must keep the
        # original callback (including comparisons of custom key objects).
        self.assertIn("lambda", compile_source("result = rows:s (_[0],)"))
        self.assertIn("_ag_itemgetter", compile_source("result = rows:s (_[0], _[1])"))

    def test_materialized_counts_preserve_effects(self):
        class Rows:
            def __iter__(self):
                yield 1
                yield 2

            def __len__(self):
                raise LookupError("length hint called")

        for run in self.functions(":n"):
            self.assertEqual(run(Rows()), 2)
        for suffix in (":l:n", ":s:n", ":l:l:n"):
            for run in self.functions(suffix):
                with self.assertRaisesRegex(LookupError, "length hint called"):
                    run(Rows())
        for run in self.functions(":s:l"):
            original = [3, 1]
            result = run(original)
            self.assertEqual(result, [1, 3])
            result.clear()
            self.assertEqual(original, [3, 1])

    def test_invalid_materialized_stage_argument_still_fails(self):
        for suffix in (":l:n 1", ":s:l 1"):
            with self.assertRaises(SyntaxError):
                compile_source("out = rows" + suffix)

    def test_filter_still_preserves_generator_exceptions(self):
        class Exhausted:
            def __bool__(self):
                raise StopIteration("from predicate")

        for suffix in (":w _:n", ":w _:l"):
            for run in self.functions(suffix):
                with self.assertRaisesRegex(RuntimeError, "generator raised StopIteration"):
                    run([Exhausted()])
