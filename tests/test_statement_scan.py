import unittest
from unittest.mock import patch

from agentlang import compiler


class StatementScanTests(unittest.TestCase):
    def test_marker_filter_matches_full_parser(self):
        programs = [
            "answer = {'p': 'abc:n'} # emit a:b\n",
            "def f(x: int):\n    return x + 1\n",
            "p = 5; j = [p]; j[0] += 1\n",
            "row = {'count': 3}\nanswer = row$count\n",
        ]
        for cmd in compiler._COMMANDS:
            for prefix in ("", "if True:\n\t", "value = 1;\f"):
                programs.append(f"{prefix}{cmd} [1,2]\n")
        args = dict(where="_", map="_", flat="[_]", common="1", top="1")
        for alias, stage in compiler._SHORT_STAGES.items():
            for sep, spelling in ((":", alias), (":", stage), ("|", stage)):
                for space in ("", "  ", "\f", "\\\r\n    "):
                    programs.append(f"out = [2,1]{sep}{space}{spelling} {args.get(stage, '')}\n")

        for source in programs:
            with self.subTest(source=source):
                # Standalone and in-memory paths share this translation step.
                expected = compiler._translate(source, "test.ag", force_scan=True)
                self.assertEqual(compiler._translate(source, "test.ag"), expected)

    def test_python_only_source_bypasses_statement_tokenizer(self):
        source = "def inc(value: int):\n    return value + 1\n"
        with patch.object(compiler.tokenize, "generate_tokens", side_effect=AssertionError):
            self.assertEqual(compiler.compile_source(source), source)
            code, scope = compiler.prepare_run(source, "test.ag")
            exec(code, scope)
            self.assertEqual(scope["inc"](2), 3)

    def test_count_retains_tokenizer_diagnostics(self):
        with self.assertRaises(SyntaxError):
            compiler.count_short_stages("value = (")
