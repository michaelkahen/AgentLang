import sys
import unittest

from agentlang import compile_source
from agentlang.compiler import prepare_run


class WordLiteralTests(unittest.TestCase):
    def both(self, source):
        exec(compile_source(source, "words.ag"), {})
        code, namespace = prepare_run(source, "words.ag")
        exec(code, namespace)

    def test_collection_type_order_duplicates_and_spelling(self):
        self.both("""
assert $[] == []
assert $() == ()
assert $(one) == ('one',)
assert $[id] == ['id']
assert $(for class True café 東京 café) == ('for', 'class', 'True', 'café', '東京', 'café')
assert $[𝐿 L हिंदी ℘ café] == ['𝐿', 'L', 'हिंदी', '℘', 'café']
def create():
    return $[foo foo]
assert create() is not create()
""")

    def test_record_pipeline_and_literal_text(self):
        self.both("""
packet = d{names=$[left right], codes=$(a b)}
assert packet$names == ['left','right']
assert packet$codes == ('a','b')
records = [1,2]:m $[id status]:l
assert records == [['id','status'], ['id','status']]
assert records[0] is not records[1]
names = $[one  # elements may span lines
          two]
assert names == ['one', 'two']
assert '$[id status] $(no parse)' == '$[id status] $(no parse)'
""")

    @unittest.skipIf(sys.version_info < (3, 12), "requires f-string expression tokens")
    def test_inside_interpolation(self):
        self.both('''assert f"actual {$[id name]}" == "actual ['id', 'name']"''')

    def test_malformed_literals(self):
        for text in ("$[a,b]", "$[x,]", "$(a + b)", "$['name']", "$[2]", "$[٣]", "$[x-y]", "$ [x]", "$([x])",
                     "$[d{x}]", "$[a", "obj$[a]", "obj $(a)", "obj?class$[a]"):
            with self.subTest(text=text), self.assertRaises(SyntaxError):
                compile_source(text, "invalid.ag")
