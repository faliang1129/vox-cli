"""ANSI 样式工具测试"""
from paicli.util.ansi import heading, section, subtle, emphasis, is_enabled


class TestAnsi:
    def test_heading(self):
        result = heading("test")
        assert isinstance(result, str)

    def test_section(self):
        result = section("test")
        assert isinstance(result, str)

    def test_subtle(self):
        result = subtle("test")
        assert isinstance(result, str)

    def test_emphasis(self):
        result = emphasis("test")
        assert isinstance(result, str)

    def test_is_enabled(self):
        assert isinstance(is_enabled(), bool)
