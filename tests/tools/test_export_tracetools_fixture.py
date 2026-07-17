import unittest

from scripts.export_tracetools_fixture import DEFAULT_EVENTS, select_records


class ExportTracetoolsFixtureTest(unittest.TestCase):
    def test_default_fixture_contains_callback_identity_linkage(self) -> None:
        required = {
            "ros2:rclcpp_callback_register",
            "ros2:rclcpp_subscription_init",
            "ros2:rclcpp_subscription_callback_added",
            "ros2:rclcpp_timer_callback_added",
            "ros2:rclcpp_timer_link_node",
            "ros2:rclcpp_service_callback_added",
        }

        self.assertTrue(required.issubset(DEFAULT_EVENTS))

    def test_selection_preserves_order_and_limits_each_event_type(self) -> None:
        records = [
            {"event_name": "ros2:callback_start", "id": 1},
            {"event_name": "ros2:rcl_publish", "id": 2},
            {"event_name": "ros2:callback_start", "id": 3},
            {"event_name": "ros2:callback_start", "id": 4},
            {"event_name": "ros2:rcl_publish", "id": 5},
        ]

        selected = select_records(records, max_per_event=2)

        self.assertEqual([record["id"] for record in selected], [1, 2, 4, 5])

    def test_selection_rejects_non_positive_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            select_records([], max_per_event=0)


if __name__ == "__main__":
    unittest.main()
