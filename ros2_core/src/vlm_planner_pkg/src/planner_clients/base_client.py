from abc import ABC, abstractmethod

from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.schema import PlannerDecision


class BasePlannerClient(ABC):
    @abstractmethod
    def plan(self, frame: CameraFrame) -> PlannerDecision:
        """Return a structured robot command for a camera frame."""
