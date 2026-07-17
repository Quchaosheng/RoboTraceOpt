import unittest

from optimizer.search.diagnosis_guided_sampler import sample_candidates


class DiagnosisGuidedSamplerTest(unittest.TestCase):
    def test_integer_candidates_are_bounded_and_reproducible(self) -> None:
        first = sample_candidates("blocking_syscall_io", limit=3, seed=7)
        second = sample_candidates("blocking_syscall_io", limit=3, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first, [{"server_delay_ms": 0}, {"server_delay_ms": 50}, {"server_delay_ms": 100}])

    def test_executor_candidates_cover_thread_bounds(self) -> None:
        self.assertEqual(
            sample_candidates("executor_queueing", limit=2, seed=1),
            [{"executor_threads": 1}, {"executor_threads": 4}],
        )

    def test_limit_must_be_positive_and_unknown_cause_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit"):
            sample_candidates("blocking_syscall_io", limit=0, seed=1)
        with self.assertRaisesRegex(ValueError, "unknown cause"):
            sample_candidates("unknown", limit=2, seed=1)


if __name__ == "__main__":
    unittest.main()
