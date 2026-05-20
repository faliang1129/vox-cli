"""CLI 解析器测试"""
from paicli.cli.parser import CliCommandParser


class TestCliCommandParser:
    def setup_method(self):
        self.parser = CliCommandParser()

    def test_is_command(self):
        assert self.parser.is_command("/help") is True
        assert self.parser.is_command("hello") is False

    def test_parse_help(self):
        result = self.parser.parse("/help")
        assert result is not None
        assert result.command == "/help"

    def test_parse_model_with_args(self):
        result = self.parser.parse('/model deepseek:deepseek-chat')
        assert result is not None
        assert result.command == "/model"
        assert "deepseek:deepseek-chat" in result.args

    def test_parse_exit(self):
        result = self.parser.parse("/exit")
        assert result.command == "/exit"

    def test_parse_not_a_command(self):
        assert self.parser.parse("hello world") is None
