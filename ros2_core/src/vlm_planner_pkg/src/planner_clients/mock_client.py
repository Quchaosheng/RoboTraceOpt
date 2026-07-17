from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.base_client import BasePlannerClient
from planner_clients.delay import apply_delay
from planner_clients.schema import PlannerDecision


class MockPlannerClient(BasePlannerClient):
    def __init__(self, delay_ms: int = 50, delay_mode: str = "sleep") -> None:
        self._delay_ms = max(delay_ms, 0)
        self._delay_mode = delay_mode

    def plan(self, frame: CameraFrame) -> PlannerDecision:
        apply_delay(self._delay_ms, self._delay_mode)

        return PlannerDecision(
            action="move_forward",
            target="front",
            speed=0.2,
            confidence=0.9,
            reason="mock planner output",
        )
