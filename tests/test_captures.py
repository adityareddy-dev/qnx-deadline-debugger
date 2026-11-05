from pathlib import Path
import tempfile
import unittest

from deadline_debugger.trace import CaptureError, analyze, compare


ROOT = Path(__file__).resolve().parent.parent
FAULT = ROOT / "captures/fault.trace"
FIXED = ROOT / "captures/fixed.trace"


class Captures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fault = analyze(FAULT)
        cls.fixed = analyze(FIXED)

    def test_recorded_comparison(self):
        report = compare(self.fault, self.fixed)
        self.assertEqual([r["summary"]["misses"] for r in report["runs"]], [20, 0])
        self.assertEqual(self.fault["summary"]["max_response_ns"], 29794727)
        self.assertEqual(self.fixed["summary"]["max_response_ns"], 4144699)
        for run in report["runs"]:
            self.assertEqual(len(run["jobs"]), 40)
            for job in run["jobs"]:
                self.assertIn("THREADY", run["raw"][job["evidence"]["ready"] - 1])
                self.assertIn("THRUNNING", run["raw"][job["evidence"]["running"] - 1])
                self.assertLessEqual(job["ready_ns"], job["running_ns"])

    def test_background_explains_first_fault_wait(self):
        job = next(j for j in self.fault["jobs"] if j["worker"] == "control" and j["job"] == 0)
        self.assertGreater(job["dispatch_wait_ns"], 25_000_000)
        self.assertGreater(job["background_during_wait_ns"] / job["dispatch_wait_ns"], .95)
        fixed = next(j for j in self.fixed["jobs"] if j["worker"] == "control" and j["job"] == 0)
        self.assertEqual(fixed["background_during_wait_ns"], 0)
        self.assertLess(fixed["dispatch_wait_ns"], 100_000)

    def corrupt(self, transform):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.trace"
            path.write_text(transform(FAULT.read_text()))
            return analyze(path)

    def test_missing_completion_is_rejected(self):
        with self.assertRaisesRegex(CaptureError, "completion"):
            self.corrupt(lambda text: "\n".join(line for line in text.splitlines()
                                               if 'STR:"DD1 complete"' not in line))

    def test_missing_job_is_rejected(self):
        with self.assertRaisesRegex(CaptureError, "Incomplete"):
            self.corrupt(lambda text: "\n".join(line for line in text.splitlines()
                                               if "DD1 finish worker=control job=0 " not in line))

    def test_duplicate_job_is_rejected(self):
        def duplicate(text):
            line = next(line for line in text.splitlines() if "DD1 finish worker=control job=0 " in line)
            return text.replace(line, line + "\n" + line)
        with self.assertRaisesRegex(CaptureError, "Duplicate job"):
            self.corrupt(duplicate)

    def test_buffer_gap_is_rejected(self):
        with self.assertRaisesRegex(CaptureError, "sequence has a gap"):
            self.corrupt(lambda text: text.replace("sequence = 2,", "sequence = 3,", 1))

    def test_multiple_cpus_are_rejected(self):
        with self.assertRaisesRegex(CaptureError, "one guest CPU"):
            self.corrupt(lambda text: text.replace("TRACE_CPU_NUM:: 1", "TRACE_CPU_NUM:: 2"))

    def test_missing_clock_reference_is_rejected(self):
        with self.assertRaisesRegex(CaptureError, "clock reference"):
            self.corrupt(lambda text: "\n".join(line for line in text.splitlines() if "DD1 sync " not in line))

    def test_missing_wide_fields_are_rejected(self):
        with self.assertRaisesRegex(CaptureError, "wide thread fields"):
            self.corrupt(lambda text: text.replace(" policy:1", ""))

    def test_reversed_runs_are_rejected(self):
        with self.assertRaisesRegex(CaptureError, "fault then fixed"):
            compare(self.fixed, self.fault)

    def test_changed_workload_is_not_a_controlled_comparison(self):
        import copy
        changed = copy.deepcopy(self.fixed)
        changed["workers"]["control"]["work_ns"] *= 2
        with self.assertRaisesRegex(CaptureError, "control work_ns"):
            compare(self.fault, changed)

    def test_strings_without_printable_str_field_are_decoded(self):
        self.assertEqual(self.fault["workers"]["background"]["work_ns"], 30_000_000)
        self.assertEqual(sum(j["worker"] == "control" for j in self.fault["jobs"]), 20)

    def test_repeat_recordings_show_the_same_fault_and_fix(self):
        repeated = compare(analyze(ROOT / "captures/repeat/fault.trace"),
                           analyze(ROOT / "captures/repeat/fixed.trace"))
        self.assertEqual([r["summary"]["misses"] for r in repeated["runs"]], [20, 0])


if __name__ == "__main__":
    unittest.main()
