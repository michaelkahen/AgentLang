import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RunArgumentsTests(unittest.TestCase):
    def test_source_path_and_arguments_in_both_dispatch_paths(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            cwd = Path(folder).resolve()
            cases = [
                ("normal.ag", ["normal.ag", "-h", "--json"], ["-h", "--json"]),
                ("normal.ag", ["normal.ag", "--", "-x"], ["-x"]),
                ("normal.ag", ["normal.ag", "start", "--", "end"], ["start", "--", "end"]),
                ("-dash.ag", ["--", "-dash.ag", "--", "-x"], ["--", "-x"]),
            ]
            for name, argv, expected in cases:
                with self.subTest(argv=argv):
                    path = cwd / name
                    path.write_text("import sys\nj [__file__, sys.path[0], sys.argv]\n")
                    call = subprocess.run(
                        [sys.executable, "-m", "agentlang", "run", *argv], cwd=cwd,
                        env=dict(os.environ, PYTHONPATH=str(root)), capture_output=True, check=True,
                    )
                    self.assertEqual(json.loads(call.stdout), [str(path), str(cwd), [str(path), *expected]])

    def test_run_uses_real_source_directory_through_a_symlink(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            cwd = Path(folder).resolve()
            scripts = cwd / "scripts"
            scripts.mkdir()
            path = scripts / "original.ag"
            path.write_text("from sibling import value\nj [__file__, value]\n")
            (scripts / "sibling.py").write_text("value = 8\n")
            link = cwd / "launch.ag"
            try:
                link.symlink_to(path)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            call = subprocess.run(
                [sys.executable, "-m", "agentlang", "run", link.name], cwd=cwd,
                env=dict(os.environ, PYTHONPATH=str(root)), capture_output=True, check=True,
            )
            self.assertEqual(json.loads(call.stdout), [str(path), 8])
