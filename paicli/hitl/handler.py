"""HITL 处理器接口"""

from typing import Protocol

from .request import ApprovalRequest
from .result import ApprovalResult


class HitlHandler(Protocol):
    def request_approval(self, req: ApprovalRequest) -> ApprovalResult:
        ...
