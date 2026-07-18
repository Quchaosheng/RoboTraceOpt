import unittest

from optimizer.experiments.campaign_schedule import build_repeated_schedule


def execution_schedule():
    return {
        "schema_version": "optimization-execution-schedule/v1",
        "cause_id": "executor_queueing",
        "action_id": "executor_threads",
        "baseline_config": {"executor_threads": 1},
        "strategy": "guided",
        "seed": 7,
        "budget": 6,
        "trials": [
            {
                "trial_index": 1,
                "status": "baseline_duplicate",
                "candidate_config": {"executor_threads": 1},
            },
            {
                "trial_index": 2,
                "status": "scheduled",
                "candidate_config": {"executor_threads": 2},
            },
            {
                "trial_index": 3,
                "status": "scheduled",
                "candidate_config": {"executor_threads": 3},
            },
            {
                "trial_index": 4,
                "status": "scheduled",
                "candidate_config": {"executor_threads": 4},
            },
            {
                "trial_index": 5,
                "status": "scheduled",
                "candidate_config": {"executor_threads": 2},
            },
            {
                "trial_index": 6,
                "status": "not_applicable",
                "candidate_config": {"frame_qos_depth": 4},
            },
        ],
    }


class CampaignScheduleTest(unittest.TestCase):
    def test_builds_deterministic_unique_balanced_blocks(self):
        first = build_repeated_schedule(
            execution_schedule(),
            repetitions=5,
            seed=20260718,
            campaign_name="executor_pilot",
        )
        second = build_repeated_schedule(
            execution_schedule(),
            repetitions=5,
            seed=20260718,
            campaign_name="executor_pilot",
        )

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "optimization-repeated-schedule/v1")
        self.assertEqual(len(first["configurations"]), 4)
        self.assertEqual(len(first["trials"]), 20)
        self.assertEqual(
            [row["role"] for row in first["configurations"]],
            ["baseline", "candidate", "candidate", "candidate"],
        )
        self.assertEqual(
            [row["candidate_config"] for row in first["configurations"]],
            [
                {"executor_threads": 1},
                {"executor_threads": 2},
                {"executor_threads": 3},
                {"executor_threads": 4},
            ],
        )
        for block in range(1, 6):
            rows = [row for row in first["trials"] if row["block_index"] == block]
            self.assertEqual(len({row["config_id"] for row in rows}), 4)
            self.assertEqual({row["position_index"] for row in rows}, {1, 2, 3, 4})
        for config in first["configurations"]:
            counts = list(config["position_counts"].values())
            self.assertLessEqual(max(counts) - min(counts), 1)
            self.assertRegex(config["config_id"], r"^cfg_[0-9a-f]{12}$")

    def test_full_rotation_places_every_config_once_in_every_position(self):
        result = build_repeated_schedule(
            execution_schedule(),
            repetitions=4,
            seed=9,
            campaign_name="executor_pilot",
        )

        for config in result["configurations"]:
            self.assertEqual(set(config["position_counts"].values()), {1})

    def test_different_seed_can_change_the_first_block(self):
        first = build_repeated_schedule(
            execution_schedule(), repetitions=4, seed=1, campaign_name="pilot"
        )
        second = build_repeated_schedule(
            execution_schedule(), repetitions=4, seed=2, campaign_name="pilot"
        )

        first_block = [
            row["config_id"] for row in first["trials"] if row["block_index"] == 1
        ]
        second_block = [
            row["config_id"] for row in second["trials"] if row["block_index"] == 1
        ]
        self.assertNotEqual(first_block, second_block)

    def test_rejects_invalid_repetitions_name_or_schema(self):
        with self.assertRaisesRegex(ValueError, "repetitions"):
            build_repeated_schedule(
                execution_schedule(), repetitions=1, seed=1, campaign_name="x"
            )
        with self.assertRaisesRegex(ValueError, "campaign name"):
            build_repeated_schedule(
                execution_schedule(), repetitions=2, seed=1, campaign_name="bad/name"
            )
        broken = execution_schedule()
        broken["schema_version"] = "wrong"
        with self.assertRaisesRegex(ValueError, "execution schedule"):
            build_repeated_schedule(broken, repetitions=2, seed=1, campaign_name="x")


if __name__ == "__main__":
    unittest.main()
