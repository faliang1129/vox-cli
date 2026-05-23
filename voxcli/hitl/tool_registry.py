"""HITL 工具注册表包装器 - 在工具执行前插入审批环节"""

import json
from typing import List, Optional

from ..tool import ToolRegistry, ToolInvocation, ToolExecutionResult
from .policy import ApprovalPolicy, ApprovalLevel
from .terminal_handler import TerminalHitlHandler
from .request import ApprovalRequest


class HitlToolRegistry:
    def __init__(self, tool_registry: ToolRegistry,
                 policy: Optional[ApprovalPolicy] = None,
                 handler: Optional[TerminalHitlHandler] = None):
        self._registry = tool_registry
        self._policy = policy or ApprovalPolicy()
        self._handler = handler or TerminalHitlHandler()

    def set_mode(self, mode: str):
        self._policy.set_mode(mode)

    def execute_tools(self, invocations: List[ToolInvocation]) -> List[ToolExecutionResult]:
        approved_invocations: List[ToolInvocation] = []

        for inv in invocations:
            level = self._policy.check(inv.name)
            if level == ApprovalLevel.NEVER:
                approved_invocations.append(inv)
                continue

            req = ApprovalRequest(
                tool_name=inv.name,
                arguments=self._parse_args(inv.arguments_json),
                reason=f"{level.value} 级别操作",
                request_id=inv.id,
            )
            result = self._handler.request_approval(req)

            if not result.approved:
                approved_invocations.append(ToolInvocation(
                    inv.id, inv.name,
                    f'{{"error": "HITL拒绝了", "reason": "{result.feedback or "用户拒绝"}"}}'
                ))
                continue

            if result.modified_args is not None:
                approved_invocations.append(ToolInvocation(
                    inv.id, inv.name, json.dumps(result.modified_args)
                ))
            else:
                approved_invocations.append(inv)

        return self._registry.execute_tools(approved_invocations)

    def __getattr__(self, name: str):
        return getattr(self._registry, name)

    @staticmethod
    def _parse_args(json_str: str) -> dict:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {}
