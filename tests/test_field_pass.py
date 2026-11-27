import sys
import unittest
from unittest.mock import patch

from agentlang import compiler


class FieldPassTests(unittest.TestCase):
    def test_false_textual_markers_do_not_retokenize(self):
        source = '''value = row?key
unused = {"count": sum([1]), "text": ":s"}
comment = "p item:m _"  # j ignored
'''
        tokenize_source = compiler.tokenize.generate_tokens
        with patch.object(compiler.tokenize, "generate_tokens", wraps=tokenize_source) as tokenizer:
            compiled = compiler.compile_source(source)
        self.assertEqual(tokenizer.call_count, 1)
        env = {"row": {"key": 17}}
        exec(compiled, env)
        self.assertEqual(env["value"], 17)

    def test_field_and_word_expressions_at_statement_boundaries(self):
        for text in (
            "value = row?key; p row$items:l",
            "def run(row):\n    return row$items:\\\n sort",
            "if True:\n    j d{count=2}",
            'results = [1, 2]:m d{value=_,flag=row?key}:l',
            "p $[left right]:s",
        ):
            with self.subTest(text=text):
                self.assertEqual(compiler._translate(text, "x.ag"),
                                 compiler._translate(text, "x.ag", force_scan=True))

    @unittest.skipUnless(sys.version_info >= (3, 12), "requires tokenized f-string expressions")
    def test_adjacent_record_and_fstring_braces(self):
        # Deliberately use the field directly after the replacement brace.
        program = '''score = 4
message = f"{{label}} {d{score}!r}"
debug = f"{d{score}=}"
'''
        env = {}
        exec(compiler.compile_source(program), env)
        self.assertEqual(env["message"], "{label} {'score': 4}")
        self.assertEqual(env["debug"], " {'score': score}={'score': 4}")

    @unittest.skipUnless(sys.version_info >= (3, 14), "requires template strings")
    def test_adjacent_record_and_template_braces(self):
        env = {}
        exec(compiler.compile_source('score = 4\nmsg = t"label {d{score}} end"'), env)
        self.assertEqual(env["msg"].strings, ("label ", " end"))
        self.assertEqual(env["msg"].interpolations[0].value, {"score": 4})
