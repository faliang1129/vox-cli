"""终端 HITL 处理器 - 在终端请求用户审批"""

import json
import sys
from typing import Optional, Set

from ..util.ansi import heading, subtle, emphasis
from .request import ApprovalRequest
from .result import ApprovalResult


class TerminalHitlHandler:
    def __init__(self):
        self._approve_all = False

    def request_approval(self, req: ApprovalRequest) -> ApprovalResult:
        if self._approve_all:
            return ApprovalResult(approved=True)

        print()
        print(heading("🪪 人工审批"))
        print(f"  工具: {emphasis(req.tool_name)}")
        print(f"  参数: {subtle(json.dumps(req.arguments, ensure_ascii=False))}")
        print(f"  原因: {req.reason}")
        print()

        while True:
            try:
                line = input("  操作 [a]批准 [A]全部批准 [r]拒绝 [s]跳过 [m]修改 → ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return ApprovalResult(approved=False, feedback="用户中断输入")

            if line in ("a", ""):
                return ApprovalResult(approved=True)
            if line == "a":
                self._approve_all = True
                return ApprovalResult(approved=True)
            if line == "r":
                return ApprovalResult(approved=False, feedback="用户拒绝")
            if line == "s":
                return ApprovalResult(approved=False, feedback="跳过")
            if line == "m":
                return self._handle_modify(req)
            print("  无效选择，请重新输入")

    def _handle_modify(self, req: ApprovalRequest) -> ApprovalResult:
        print(f"  输入修改后的参数 (JSON)，空行取消修改:")
        try:
            modified = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult(approved=False, feedback="用户中断输入")

        if not modified:
            return ApprovalResult(approved=False, feedback="取消修改")

        try:
            new_args = json.loads(modified)
            if not isinstance(new_args, dict):
                raise ValueError
            return ApprovalResult(approved=True, modified_args=new_args)
        except (json.JSONDecodeError, ValueError):
            print("  JSON 格式无效")
            return ApprovalResult(approved=False, feedback="JSON 格式无效")
