import unittest

from optimizer.action_registry.registry import (
    available_actions,
    actions_for_cause,
    validate_action,
)


class ActionRegistryTest(unittest.TestCase):
    def test_maps_known_causes_to_bounded_actions(self) -> None:
        actions = actions_for_cause("blocking_syscall_io")
        self.assertEqual([item["action_id"] for item in actions], ["server_delay_ms"])
        self.assertEqual(actions[0]["bounds"], {"min": 0, "max": 100})

    def test_exposes_stable_action_catalog_without_duplicates(self) -> None:
        catalog = available_actions()
        ids = [item["action_id"] for item in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("executor_threads", ids)
        self.assertIn("frame_qos_depth", ids)

    def test_rejects_action_outside_diagnosed_cause_or_bounds(self) -> None:
        validate_action("blocking_syscall_io", "server_delay_ms", 50)
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_action("blocking_syscall_io", "frame_qos_depth", 10)
        with self.assertRaisesRegex(ValueError, "bounds"):
            validate_action("blocking_syscall_io", "server_delay_ms", 101)

    def test_unknown_cause_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown cause"):
            actions_for_cause("made_up_cause")

    def test_executor_queueing_maps_to_thread_count(self) -> None:
        actions = actions_for_cause("executor_queueing")
        self.assertEqual([item["action_id"] for item in actions], ["executor_threads"])
        self.assertEqual(actions[0]["bounds"], {"min": 1, "max": 4})
        validate_action("executor_queueing", "executor_threads", 2)
        with self.assertRaisesRegex(ValueError, "bounds"):
            validate_action("executor_queueing", "executor_threads", 0)


if __name__ == "__main__":
    unittest.main()
