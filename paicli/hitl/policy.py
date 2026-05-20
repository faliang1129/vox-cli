"""HITL 审批策略 - 定义哪些工具需要人工审批"""

from enum import Enum


class ApprovalLevel(Enum):
    ALWAYS = "ALWAYS"           # 总是需要审批
    DANGEROUS = "DANGEROUS"     # 危险操作需要审批
    NEVER = "NEVER"             # 不需要审批


# 危险工具列表（与 AuditLog 保持一致）
_DANGEROUS_TOOLS = {"write_file", "execute_command", "create_project"}


class ApprovalPolicy:
    def __init__(self, mode: str = "auto"):
        self._mode = mode  # "auto", "always", "never"

    def check(self, tool_name: str) -> ApprovalLevel:
        if self._mode == "always":
            return ApprovalLevel.ALWAYS
        if self._mode == "never":
            return ApprovalLevel.NEVER
        return ApprovalLevel.DANGEROUS if tool_name in _DANGEROUS_TOOLS else ApprovalLevel.NEVER

    def set_mode(self, mode: str):
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode
