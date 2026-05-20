"""LLM 模块测试"""
from paicli.llm.base import Message, ChatResponse, ToolCall, ToolDef
from paicli.llm.factory import create_from_config


class TestMessage:
    def test_system(self):
        m = Message.system("be helpful")
        assert m.role == "system"
        assert m.content == "be helpful"

    def test_user(self):
        m = Message.user("hello")
        assert m.role == "user"

    def test_assistant(self):
        m = Message.assistant(content="hi")
        assert m.role == "assistant"
        assert m.content == "hi"

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(id="c1", name="read_file", arguments='{"path":"."}')
        m = Message.assistant(content="", tool_calls=[tc])
        assert len(m.tool_calls) == 1
        assert m.tool_calls[0].name == "read_file"

    def test_tool(self):
        m = Message.tool("c1", "result data")
        assert m.role == "tool"
        assert m.tool_call_id == "c1"


class TestChatResponse:
    def test_no_tool_calls(self):
        r = ChatResponse(content="answer")
        assert r.has_tool_calls is False

    def test_with_tool_calls(self):
        r = ChatResponse(tool_calls=[ToolCall(id="c1", name="read_file", arguments="{}")])
        assert r.has_tool_calls is True


class TestFactory:
    def test_create_from_config(self):
        client = create_from_config()
        if client:
            assert client.model_name
            assert client.provider_name

    def test_chat_basic(self):
        client = create_from_config()
        if client:
            resp = client.chat([Message.user("回复一个字：好")])
            assert resp.content
            assert "好" in resp.content
