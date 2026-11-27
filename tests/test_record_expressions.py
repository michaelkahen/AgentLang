import ast
import sys
import unittest

from agentlang import compile_python, compile_source
from agentlang.compiler import prepare_run


class RecordExpressionTests(unittest.TestCase):
    def run_both(self, source):
        exec(compile_source(source, "records.ag"), {})
        code, namespace = prepare_run(source, "records.ag")
        exec(code, namespace)

    def test_optional_lookup_dispatches_one_get(self):
        self.run_both("""
calls = []
class Probe:
    def get(self, *args):
        calls.append(args)
        return 0
def item():
    calls.append('item')
    return Probe()
assert item()?class == 0
assert calls == ['item', ('class',)]
assert {}?missing is None
assert {'class': {'name': False}}?class$name is False
rows = [{'keep': False}, {}, {'keep': True}]
result = rows:w _?keep:l
assert result == [{'keep': True}]
for absent in (None, 1):
    try:
        absent?item
    except AttributeError:
        pass
    else:
        raise AssertionError('object has no get method')
""")
        # A dot following an integer must be lexically separated.
        self.assertEqual(ast.dump(ast.parse(compile_source("24?key"))),
                         ast.dump(ast.parse("(24).get('key')")))

    def test_record_expressions_preserve_order_and_duplicates(self):
        self.run_both("""
calls = []
def mark(value):
    calls.append(value)
    return value
tag = 'ok'
packet = d{tag,
           value=mark(1), nested=d{tag, optional={}?ignored},
           value=mark(2), items=[(i, i+1) for i in range(2)],}
assert list(packet) == ['tag', 'value', 'nested', 'items']
assert packet == {'tag':'ok', 'value':2, 'nested':{'tag':'ok', 'optional':None},
                  'items':[(0,1),(1,2)]}
assert calls == [1, 2]
""")

    def test_expression_boundaries(self):
        self.run_both("""
value = 5
record = d{callback=lambda arg, scale=2: arg * scale,
           pair=(value, value), title='?value d{key=value}',
           value # preserve comments between a field and its value
               =value+1}
assert record['callback'](3) == 6
assert record['pair'] == (5, 5)
assert record['title'] == '?value d{key=value}'
assert record['value'] == 6
assert d{} == {}
assert d{value={'lambda':4}?lambda, next=5} == {'value':4, 'next':5}
assert list(d{items=(v for v in [3, 4])}?items) == [3, 4]
""")

    @unittest.skipIf(sys.version_info < (3, 12), "requires f-string expression tokens")
    def test_fstrings(self):
        self.run_both('''
row = {'value': 8}
packet = d{title=f"key, d{{item}} {row?value}", size=len(row)}
assert packet == {'title':'key, d{item} 8', 'size':1}
''')

    @unittest.skipIf(sys.version_info < (3, 14), "requires template strings")
    def test_template_strings(self):
        self.run_both('''
row = {'name': 'ok'}
packet = d{title=t"field, {row?name}", name=row?name}
assert packet['title'].interpolations[0].value == packet['name'] == 'ok'
''')

    def test_diagnostics_and_python_control(self):
        for source in ("record ?field", "record? field", "?field", "record?0",
                       "row?field = 0", "d{left, 1}", "d{a+1}", "d{a=}", "d{a,,b}",
                       "d{x=y for y in rows}", "d{x=**foo}"):
            with self.subTest(source=source), self.assertRaises(SyntaxError) as error:
                compile_source(source, "bad.ag")
            self.assertEqual(error.exception.filename, "bad.ag")
        for source in ("a?field", "d{copy=left}"):
            with self.subTest(source=source), self.assertRaises(SyntaxError):
                compile_python(source)
