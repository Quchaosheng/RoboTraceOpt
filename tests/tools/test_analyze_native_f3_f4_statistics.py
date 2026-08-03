from __future__ import annotations

import unittest

from scripts.analyze_native_f3_f4_statistics import exact_two_sided_sign_p


class NativeF3F4StatisticsTest(unittest.TestCase):
    def test_exact_sign_test_for_ten_same_direction_pairs(self) -> None:
        self.assertAlmostEqual(exact_two_sided_sign_p([1.0] * 10), 0.001953125)
        self.assertAlmostEqual(exact_two_sided_sign_p([-1.0] * 10), 0.001953125)

    def test_exact_sign_test_ignores_zero_differences(self) -> None:
        self.assertEqual(exact_two_sided_sign_p([1.0, -1.0, 0.0]), 1.0)
        self.assertIsNone(exact_two_sided_sign_p([0.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
