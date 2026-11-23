"""Regression tests for property identity, bounded verdicts and immutable repair inputs."""
import copy
import gzip
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/stage2"))
from check_case import classify, load_case, normalize
from freeze import check_command, validate

CASE = ROOT / "cases/split_counter"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        _, self.gamma, self.phi = load_case(CASE)
        self.raw = gzip.decompress((CASE / "evidence/old/result.json.gz").read_bytes())
        self.messages = json.loads(self.raw)
        self.rows = next(m["result"] for m in self.messages if "result" in m)

    def test_real_trace_matches_original_document(self):
        verdict, row = classify(self.raw, 10, self.phi)
        stored = json.loads((CASE / "evidence/old/cex0.json").read_bytes())
        self.assertEqual(verdict["classification"], "VIOLATION")
        self.assertEqual(stored, normalize(row, self.phi, self.gamma, stored["input_sha256"], "result.json.gz"))

    def test_missing_or_duplicate_property_rejected(self):
        for empty in (True, False):
            with self.subTest(empty=empty):
                messages = copy.deepcopy(self.messages)
                rows = next(m["result"] for m in messages if "result" in m)
                if empty:
                    rows.clear()
                else:
                    rows.append(copy.deepcopy(rows[0]))
                with self.assertRaises(ValueError):
                    classify(json.dumps(messages), 10, self.phi)

    def test_wrong_assertion_location_rejected(self):
        self.rows[0]["sourceLocation"]["line"] = "1"
        with self.assertRaises(ValueError):
            classify(json.dumps(self.messages), 10, self.phi)

    def test_trailing_diagnostics_and_wrong_exit_rejected(self):
        with self.assertRaises(ValueError):
            classify(self.raw + b"solver diagnostic", 10, self.phi)
        with self.assertRaises(ValueError):
            classify(self.raw, 0, self.phi)

    def test_failure_needs_source_matched_trace(self):
        target = self.rows[0]
        target["trace"] = [s for s in target["trace"] if s["stepType"] != "failure"]
        with self.assertRaises(ValueError):
            normalize(target, self.phi, self.gamma, {"program.c": "dummy"}, "result.json.gz")

    def test_unwind_and_unrelated_failures_do_not_become_bounded_passes(self):
        self.rows[0]["status"] = "SUCCESS"
        for prop, expected in (("main.unwind.0", "INCOMPLETE_UNWINDING"), ("library.assertion.1", "UNKNOWN")):
            with self.subTest(prop=prop):
                messages = copy.deepcopy(self.messages)
                rows = next(m["result"] for m in messages if "result" in m)
                rows.append({"property":prop, "status":"FAILURE"})
                verdict, _ = classify(json.dumps(messages), 10, self.phi)
                self.assertEqual(verdict["classification"], expected)

    def test_inconclusive_is_unknown(self):
        self.rows[0]["status"] = "UNKNOWN"
        self.messages[-1]["cProverStatus"] = "inconclusive"
        self.assertEqual(classify(json.dumps(self.messages),5,self.phi)[0]["classification"], "UNKNOWN")

    def test_recorded_verifier_flags_must_match_gamma(self):
        run = json.loads((CASE / "evidence/old/run.json").read_bytes())
        command = run["runs"]["verify"]["command"].copy()
        command[command.index("--unwind") + 1] = "1"
        with self.assertRaisesRegex(ValueError, "arguments"):
            check_command("verify", command, self.gamma)

    def test_protected_harness_and_output_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / CASE.name
            shutil.copytree(CASE, case)
            extra = case / "candidate/extra.c"
            extra.write_text("int extra;\n")
            with self.assertRaisesRegex(ValueError, "allowlist"):
                validate(case)
            extra.unlink()
            with (case / "harness.c").open("ab") as out:
                out.write(b"\n")
            with self.assertRaisesRegex(ValueError, "Protected"):
                load_case(case)


if __name__ == "__main__":
    unittest.main()
