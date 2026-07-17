from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerDecision:
    action: str
    target: str
    speed: float
    confidence: float
    reason: str
