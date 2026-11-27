import csv
from pathlib import Path
import tempfile
import unittest

from agentlang.compiler import compile_python, compile_source, prepare_run
from agentlang.helpers import csvrows


class CsvRowsTests(unittest.TestCase):
    def test_csv_reader_contract(self):
        fixtures = {
            "empty": b"",
            "header_only": b"first,second\n\n",
            "blank_header": b"\nx,y\n\n",
            "ragged": b'a,b,a\nred\n\n1,2,3,4,5\n""\n',
            "quoted": 'a,b\r\n"a,é","x\r\ny"\r\n"""quoted""",\r\n'.encode(),
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.csv"
            for label, content in fixtures.items():
                with self.subTest(label=label):
                    path.write_bytes(content)
                    with path.open(encoding="utf-8", newline="") as stream:
                        expected = [list(row.items()) for row in csv.DictReader(stream)]
                    self.assertEqual([list(row.items()) for row in csvrows(path)], expected)

    def test_decode_and_parser_errors_propagate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.csv"
            path.write_bytes(b"id\n\xff\n")
            with self.assertRaises(UnicodeDecodeError):
                csvrows(path)
            path.write_bytes(b"id\n" + b"x" * (csv.field_size_limit() + 1))
            with self.assertRaises(csv.Error):
                csvrows(path)

    def test_helper_bindings_survive_shadowed_builtins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.csv"
            path.write_bytes(b"a,b\nx\n1,2,3\n")
            source = f"open = next = len = dict = zip = None\nrows = c({str(path)!r})"
            prepared, bindings = prepare_run(source, "test.ag")
            for code, namespace in ((prepared, bindings), (compile_source(source), {}),
                                    (compile_python(source), {})):
                exec(code, namespace)
                self.assertEqual(namespace["rows"], [{"a": "x", "b": None},
                                                     {"a": "1", "b": "2", None: ["3"]}])


if __name__ == "__main__":
    unittest.main()
