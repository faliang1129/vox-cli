"""HITL 审批结果"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ApprovalResult:
    approved: bool
    modified_args: Optional[dict] = None
    feedback: Optional[str] = None
