"""Own mutable schemas per tool instance; preserve native class defaults."""
from copy import deepcopy
from .state_constraints import ActionState


class IsolatedActionState(ActionState):
    def refresh(self, agent: object, all_tools: dict) -> None:
        for tool in all_tools.values():
            tool.inputs=deepcopy(tool.inputs)
        super().refresh(agent,all_tools)
