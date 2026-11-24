"""Check fixture and oracle compatibility with the frozen benchmark and trace contract."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.long.runtime.run import fixture_manifest
from benchmarks.patterns.evaluation.cases import PILOT_PROMPTS, TRACE_NAME, TRACE_PROMPT, matches, prepare


ROOT = Path(__file__).resolve().parents[3]


class FixtureTests(unittest.TestCase):
    def test_original_fixtures_are_byte_identical(self):
        frozen = json.loads((ROOT / "benchmarks/long/runtime/results.json").read_text())["fixtures"]
        for task in PILOT_PROMPTS:
            for variant, old in frozen[task].items():
                with self.subTest(task=task, variant=variant), tempfile.TemporaryDirectory() as temp:
                    cwd = Path(temp)
                    case = prepare(task, variant, cwd)
                    self.assertEqual(fixture_manifest(cwd, case["stdin"], case["expected"]), old)

    def test_original_edge_fixture_manifests(self):
        # Edge cases were graded but not timed in 934d61a, so the old timing record omits them.
        digests = {
            "movie_credits": "b82794d46055ebf21194505ca9ea7758cc6f0210cd158fcb561df11695c7df62",
            "knn_grid": "e73de734db23e051d1aac71d1bc589fd484484fd55b74a1905b1b6215f21a763",
            "fixture_pack": "e7aa03b3873cabc2720f2cfd33faa6bb2214e39a73648eef1904d54f97740db4",
        }
        for task, sha in digests.items():
            with self.subTest(task=task), tempfile.TemporaryDirectory() as temp:
                cwd = Path(temp)
                case = prepare(task, "edges", cwd)
                manifest = fixture_manifest(cwd, case["stdin"], case["expected"])
                wire = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(wire).hexdigest(), sha)

    def test_heldout_contract_and_closed_base(self):
        self.assertEqual(hashlib.sha256(TRACE_PROMPT.encode()).hexdigest(),
                         "808b406ddfa1c0235267017af04724a4370f5ca62b09488c81c5f4152bb0b37d")
        with tempfile.TemporaryDirectory() as temp:
            expected = prepare(TRACE_NAME, "base", Path(temp))["expected"]
        self.assertEqual(expected["totals"], {"ok": 1, "failed": 1, "open": 1, "commands": 1,
                                               "input_tokens": 12, "output_tokens": 4})
        self.assertEqual([(r["run"], r["status"], r["last_message"]) for r in expected["runs"]],
                         [("alpha", "open", "still working"), ("beta", "ok", "ready"),
                          ("gamma", "failed", "bad input")])

    def test_profile_totals_and_strict_types(self):
        with tempfile.TemporaryDirectory() as temp:
            expected = prepare(TRACE_NAME, "profile", Path(temp))["expected"]
        self.assertEqual(len(expected["runs"]), 1200)
        for key in ("commands", "input_tokens", "output_tokens"):
            self.assertEqual(expected["totals"][key], sum(run[key] for run in expected["runs"]))
        self.assertFalse(matches(b'{"commands": true}', {"commands": 1}))
        self.assertFalse(matches(b'{"commands": 1.0}', {"commands": 1}))
        self.assertFalse(matches(b'{"commands": 3,"commands":1}', {"commands": 1}))


if __name__ == "__main__":
    unittest.main()
