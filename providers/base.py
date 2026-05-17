from abc import ABC, abstractmethod
from harness.protocols import Step, StepResult, TaskPlan


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderBase(ABC):
    name:     str
    roles:    list[str]   # ["planner"] | ["executor"] | ["planner", "executor"]
    priority: int

    def supports_role(self, role: str) -> bool:
        return role in self.roles

    def planner_model_for(self, task_type: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_plan(self, task_md: str, task_type: str) -> TaskPlan: ...

    @abstractmethod
    def execute_step(
        self, step: Step, task_md: str, plan_summary: str, task_type: str
    ) -> StepResult: ...
