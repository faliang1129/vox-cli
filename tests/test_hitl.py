"""HITL 模块测试"""
from paicli.hitl.request import ApprovalRequest
from paicli.hitl.result import ApprovalResult
from paicli.hitl.policy import ApprovalPolicy
from paicli.hitl.tool_registry import HitlToolRegistry
from paicli.tool import ToolRegistry


class TestApprovalPolicy:
    def test_default_mode(self):
        p = ApprovalPolicy()
        assert p.mode == "auto"

    def test_set_mode(self):
        p = ApprovalPolicy()
        p.set_mode("always")
        assert p.mode == "always"
        p.set_mode("never")
        assert p.mode == "never"


class TestDataClasses:
    def test_approval_request(self):
        req = ApprovalRequest(tool_name="write_file",
                             arguments={"path": "/x"},
                             reason="write file")
        assert req.tool_name == "write_file"

    def test_approval_result(self):
        res = ApprovalResult(approved=True, feedback="ok")
        assert res.approved is True
        assert res.feedback == "ok"


class TestHitlToolRegistry:
    def test_wraps_all_tools(self):
        reg = ToolRegistry()
        htr = HitlToolRegistry(reg)
        defs = htr.get_tool_definitions()
        assert len(defs) == 8
