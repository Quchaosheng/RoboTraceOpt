import unittest

from experiments.physical_can.interfaces import validate_physical_can_pair


def can_link(name: str, *, bitrate: int = 500000) -> dict:
    return {
        "ifname": name,
        "flags": ["UP", "LOWER_UP"],
        "linkinfo": {
            "info_kind": "can",
            "info_data": {
                "state": "ERROR-ACTIVE",
                "bittiming": {"bitrate": bitrate},
            },
        },
    }


class PhysicalCanInterfaceTest(unittest.TestCase):
    def test_accepts_distinct_up_links_with_matching_bitrate(self) -> None:
        pair = validate_physical_can_pair(
            [can_link("can0"), can_link("can1")],
            runtime_interface="can0",
            peer_interface="can1",
            bitrate=500000,
        )

        self.assertEqual(pair["runtime"]["ifname"], "can0")
        self.assertEqual(pair["peer"]["ifname"], "can1")
        self.assertEqual(pair["bitrate"], 500000)

    def test_rejects_same_virtual_down_bus_off_or_wrong_bitrate_links(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate_physical_can_pair(
                [can_link("can0")],
                runtime_interface="can0",
                peer_interface="can0",
                bitrate=500000,
            )

        virtual = can_link("can1")
        virtual["linkinfo"]["info_kind"] = "vcan"
        down = can_link("can1")
        down["flags"] = []
        bus_off = can_link("can1")
        bus_off["linkinfo"]["info_data"]["state"] = "BUS-OFF"
        wrong_bitrate = can_link("can1", bitrate=250000)
        for record, message in (
            (virtual, "physical CAN"),
            (down, "UP"),
            (bus_off, "BUS-OFF"),
            (wrong_bitrate, "bitrate"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_physical_can_pair(
                        [can_link("can0"), record],
                        runtime_interface="can0",
                        peer_interface="can1",
                        bitrate=500000,
                    )

    def test_rejects_missing_or_unreported_bitrate(self) -> None:
        missing_bitrate = can_link("can1")
        del missing_bitrate["linkinfo"]["info_data"]["bittiming"]
        with self.assertRaisesRegex(ValueError, "bitrate"):
            validate_physical_can_pair(
                [can_link("can0"), missing_bitrate],
                runtime_interface="can0",
                peer_interface="can1",
                bitrate=500000,
            )

    def test_accepts_unreported_slcan_bitrate_with_process_evidence(self) -> None:
        runtime = can_link("can1")
        peer = can_link("can2")
        runtime["linkinfo"]["info_data"]["bittiming"]["bitrate"] = 0
        peer["linkinfo"]["info_data"]["bittiming"]["bitrate"] = 0

        pair = validate_physical_can_pair(
            [runtime, peer],
            runtime_interface="can1",
            peer_interface="can2",
            bitrate=500000,
            slcand_processes=[
                "9348 slcand -o -c -s6 /dev/ttyACM0 can1",
                "9351 slcand -o -c -s6 /dev/ttyACM1 can2",
            ],
        )

        self.assertEqual(pair["bitrate_evidence"]["runtime"]["source"], "slcand")
        self.assertEqual(pair["bitrate_evidence"]["peer"]["speed_code"], "s6")

    def test_rejects_wrong_or_ambiguous_slcan_process_evidence(self) -> None:
        runtime = can_link("can1")
        peer = can_link("can2")
        for link in (runtime, peer):
            link["linkinfo"]["info_data"]["bittiming"]["bitrate"] = 0
        base = ["9351 slcand -o -c -s6 /dev/ttyACM1 can2"]
        for processes in (
            ["9348 slcand -o -c -s5 /dev/ttyACM0 can1", *base],
            [
                "9348 slcand -o -c -s6 /dev/ttyACM0 can1",
                "9349 slcand -o -c -s6 /dev/ttyACM2 can1",
                *base,
            ],
        ):
            with self.subTest(processes=processes):
                with self.assertRaisesRegex(ValueError, "slcand process"):
                    validate_physical_can_pair(
                        [runtime, peer],
                        runtime_interface="can1",
                        peer_interface="can2",
                        bitrate=500000,
                        slcand_processes=processes,
                    )


if __name__ == "__main__":
    unittest.main()
