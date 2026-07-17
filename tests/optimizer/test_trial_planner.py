import unittest

from optimizer.search.trial_planner import build_trial_plan


class TrialPlannerTest(unittest.TestCase):
    def test_guided_plan_uses_only_diagnosed_action(self) -> None:
        plan = build_trial_plan(
            "blocking_syscall_io", strategy="guided", budget=3, seed=7
        )
        self.assertEqual(plan["schema_version"], "optimization-trial-plan/v1")
        self.assertTrue(plan["diagnosis_constrained"])
        self.assertEqual(
            [trial["candidate_config"] for trial in plan["trials"]],
            [{"server_delay_ms": 0}, {"server_delay_ms": 50}, {"server_delay_ms": 100}],
        )

    def test_random_plan_is_reproducible_and_budgeted(self) -> None:
        first = build_trial_plan(
            "application_compute_delay", strategy="random", budget=5, seed=13
        )
        second = build_trial_plan(
            "application_compute_delay", strategy="random", budget=5, seed=13
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first["trials"]), 5)
        self.assertTrue(all("planner_delay_ms" in trial["candidate_config"] for trial in first["trials"]))

    def test_guided_boolean_plan_preserves_requested_budget(self) -> None:
        plan = build_trial_plan(
            "executor_queueing", strategy="guided", budget=5, seed=9
        )
        self.assertEqual(len(plan["trials"]), 5)
        self.assertEqual(
            {trial["candidate_config"]["executor_contention_enabled"] for trial in plan["trials"]},
            {False, True},
        )

    def test_unguided_plan_exposes_global_action_search(self) -> None:
        plan = build_trial_plan(
            "blocking_syscall_io", strategy="unguided_random", budget=6, seed=3
        )
        action_ids = {trial["action_id"] for trial in plan["trials"]}
        self.assertFalse(plan["diagnosis_constrained"])
        self.assertIn("server_delay_ms", action_ids)
        self.assertGreater(len(action_ids), 1)

    def test_rejects_invalid_strategy_or_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "strategy"):
            build_trial_plan("blocking_syscall_io", strategy="grid", budget=3, seed=1)
        with self.assertRaisesRegex(ValueError, "budget"):
            build_trial_plan("blocking_syscall_io", strategy="guided", budget=0, seed=1)


if __name__ == "__main__":
    unittest.main()
