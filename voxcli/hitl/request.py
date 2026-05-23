"""HITL 审批请求"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ApprovalRequest:
    tool_name: str
    arguments: Dict[str, str]
    reason: str
    request_id: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
