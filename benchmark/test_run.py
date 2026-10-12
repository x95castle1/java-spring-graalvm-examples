import unittest
from pathlib import Path
import tempfile
from native_check import verify_elf
from run import comparison_rows, expected_checksum, percentile, reduction, summarize, verify_output


class BenchmarkTest(unittest.TestCase):
    def test_checks_unsigned_shift_and_signed_overflow(self):
        self.assertEqual(325410109145977306, expected_checksum(1))
        self.assertEqual(-7896971328211040135, expected_checksum(2))

    def test_rejects_fast_but_incorrect_output(self):
        with self.assertRaisesRegex(ValueError, "Incorrect application"):
            verify_output({}, 100_000, 1)

    def test_rejects_script_or_jar_as_native_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "application"
            for data in (b"#!/bin/sh\njava -jar app.jar", b"PK\x03\x04jar", b""):
                artifact.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "ELF"):
                    verify_elf(artifact)

    def test_reports_interpolated_percentiles_and_units(self):
        records = [
            {"elapsed_ms": 10, "peak_rss_kib": 1024, "user_cpu_seconds": 0.01, "system_cpu_seconds": 0},
            {"elapsed_ms": 20, "peak_rss_kib": 2048, "user_cpu_seconds": 0.02, "system_cpu_seconds": 0},
        ]
        summary = summarize(records)
        self.assertEqual(15, summary["completion_ms"]["median"])
        self.assertEqual(19.5, summary["completion_ms"]["p95"])
        self.assertEqual(1.5, summary["peak_rss_mib"]["median"])
        self.assertEqual(10, percentile([10], 95))

    def test_comparison_preserves_regressions_and_sample_counts(self):
        records = [{"elapsed_ms": 20, "peak_rss_kib": 2048, "user_cpu_seconds": 0.02, "system_cpu_seconds": 0}]
        baseline = summarize(records, "baseline")
        records[0]["elapsed_ms"] = 25
        records[0]["peak_rss_kib"] = 1024
        cache = summarize(records, "workload-cache")
        rows = comparison_rows({"baseline": baseline, "workload-cache": cache})
        self.assertEqual("1", rows[2][1])
        self.assertEqual("-25.0%", rows[2][5])
        self.assertEqual("+50.0%", rows[2][6])
        self.assertEqual(20, reduction(100, 80))


if __name__ == "__main__":
    unittest.main()
