"""工具注册表测试"""
import json
import tempfile
from pathlib import Path
from paicli.tool import ToolRegistry, ToolDef, ToolInvocation, ToolExecutionResult


class TestToolRegistry:
    def test_all_tools_registered(self):
        reg = ToolRegistry()
        defs = reg.get_tool_definitions()
        names = {t.name for t in defs}
        expected = {"read_file", "write_file", "list_dir", "execute_command",
                    "create_project", "search_code", "web_search", "web_fetch"}
        assert names == expected
        assert len(defs) == 8

    def test_get_tool_definitions_returns_tooldef_objects(self):
        reg = ToolRegistry()
        for t in reg.get_tool_definitions():
            assert isinstance(t, ToolDef)
            assert t.name
            assert t.description
            assert "type" in t.parameters

    def test_execute_command(self):
        reg = ToolRegistry()
        res = reg.execute_tool("execute_command", '{"command":"echo hello"}')
        assert "hello" in res

    def test_read_file(self):
        reg = ToolRegistry()
        res = reg.execute_tool("read_file", f'{{"path":"{__file__}"}}')
        assert "ToolRegistry" in res

    def test_list_dir(self):
        reg = ToolRegistry()
        res = reg.execute_tool("list_dir", '{"path":"."}')
        assert "[D]" in res or "[F]" in res

    def test_write_and_read_file(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            reg.set_project_path(td)
            res = reg.execute_tool("write_file", f'{{"path":"{td}/test.txt","content":"hello world"}}')
            assert "文件已写入" in res
            res = reg.execute_tool("read_file", f'{{"path":"{td}/test.txt"}}')
            assert "hello world" in res

    def test_policy_blocks_dangerous_command(self):
        reg = ToolRegistry()
        res = reg.execute_tool("execute_command", '{"command":"sudo rm -rf /"}')
        assert "🛡️" in res

    def test_parallel_execution(self):
        reg = ToolRegistry()
        invocations = [
            ToolInvocation("t1", "execute_command", '{"command":"echo a"}'),
            ToolInvocation("t2", "execute_command", '{"command":"echo b"}'),
            ToolInvocation("t3", "execute_command", '{"command":"echo c"}'),
        ]
        results = reg.execute_tools(invocations)
        assert len(results) == 3
        outputs = [r.result for r in results]
        assert any("a" in o for o in outputs)

    def test_create_project_python(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            reg.set_project_path(td)
            res = reg.execute_tool("create_project", '{"name":"p1","type":"python"}')
            assert "项目已创建" in res
            assert Path(td, "p1/main.py").exists()

    def test_create_project_java(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            reg.set_project_path(td)
            res = reg.execute_tool("create_project", '{"name":"j1","type":"java"}')
            assert "项目已创建" in res
            assert Path(td, "j1/pom.xml").exists()

    def test_create_project_node(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            reg.set_project_path(td)
            res = reg.execute_tool("create_project", '{"name":"n1","type":"node"}')
            assert "项目已创建" in res
            assert Path(td, "n1/package.json").exists()
