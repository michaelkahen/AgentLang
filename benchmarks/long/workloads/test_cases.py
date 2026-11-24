"""Regression checks for the independent long-task oracles."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from benchmarks.pilot.runtime.scale import FILES, prepare_examples
from benchmarks.long.workloads.cases import matches, prepare


class OracleTests(unittest.TestCase):
    def test_json(self):
        expected = {"n": 1, "records": []}
        self.assertTrue(matches(b'{"records": [], "n": 1}\n', expected))
        for text in ('{"n":true,"records":[]}', '{"n":1.0,"records":[]}',
                     '{"n":1,"n":1,"records":[]}', 'NaN', '{"n":1,"records":[]} extra'):
            self.assertFalse(matches(text, expected))

    def test_movie_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare("movie_credits", "audit", Path(tmp))["expected"]
        self.assertEqual(report["films"], 4)
        self.assertEqual(report["credited_films"], 3)
        self.assertEqual(report["appearances"], 8)
        self.assertEqual([(p["id"], p["credits"], p["movies"]) for p in report["leaders"]],
                         [(3, 2, 2), (4, 2, 2), (7, 2, 2), (1, 2, 1)])

    def test_knn_zero_distances(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare("knn_grid", "audit", Path(tmp))["expected"]
        # At k=5 three nonzero neighbors outvote two center labels only with
        # uniform weights. All fifteen non-center labels are correctly predicted.
        self.assertEqual([c["correct"] for c in report["grid"]],
                         [15, 15, 15, 15, 15, 15, 15, 15, 16, 15, 16, 15])
        self.assertEqual(report["best"], 8)
        self.assertEqual(report["predictions"], ["z"] * 4)
        self.assertEqual(report["test_correct"], 2)

    def test_pack_matches_original_files(self):
        for variant in ("base", "edges", "profile", "audit"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                seed, scaled = Path(tmp, "seed"), Path(tmp, "scaled")
                bundle = prepare("fixture_pack", variant, seed)
                directory, sizes = prepare_examples(seed, scaled, int(bundle["stdin"]), tuple(FILES))
                for task, expected in bundle["expected"].items():
                    digest = hashlib.sha256((directory / (task + ".out")).read_bytes()).hexdigest()
                    self.assertEqual(sizes[task]["records"], expected["records"])
                    self.assertEqual(sizes[task]["input_bytes"], expected["bytes"])
                    self.assertEqual(sizes[task]["input_sha256"], expected["input_sha256"])
                    self.assertEqual(digest, expected["golden_sha256"])


if __name__ == "__main__":
    unittest.main()
