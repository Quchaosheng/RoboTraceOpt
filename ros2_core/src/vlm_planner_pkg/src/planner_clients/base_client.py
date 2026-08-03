from abc import ABC, abstractmethod
import time

from ai_robot_runtime_interfaces.msg import CameraFrame

from planner_clients.model_contract import (
    ModelRequest,
    ModelResult,
    classify_backend_error,
    response_fingerprint,
)
from planner_clients.schema import PlannerDecision


class BasePlannerClient(ABC):
    @abstractmethod
    def plan(self, frame: CameraFrame) -> PlannerDecision:
        """Return a structured robot command for a camera frame."""

    def plan_with_request(
        self, frame: CameraFrame, request: ModelRequest
    ) -> ModelResult:
        """Run the legacy backend behind a versioned, failure-safe contract."""

        started_ns = time.monotonic_ns()
        try:
            decision = self.plan(frame)
        except Exception as error:
            return ModelResult(
                backend=self.backend_name,
                decision=None,
                latency_ns=time.monotonic_ns() - started_ns,
                error_code=classify_backend_error(error),
            )
        result = ModelResult(
            backend=self.backend_name,
            decision=decision,
            latency_ns=time.monotonic_ns() - started_ns,
        )
        return ModelResult(
            backend=result.backend,
            decision=result.decision,
            latency_ns=result.latency_ns,
            response_fingerprint=response_fingerprint(result),
        )

    @property
    def backend_name(self) -> str:
        return self.__class__.__name__.replace("PlannerClient", "").lower()
