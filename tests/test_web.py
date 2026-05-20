"""Web 模块测试"""
from paicli.web.network_policy import NetworkPolicy
from paicli.web.fetch_result import FetchResult
from paicli.web.result import SearchResult
from paicli.web.extractor import HtmlExtractor
from paicli.web.fetcher import WebFetcher
from paicli.web.factory import SearchProviderFactory


class TestNetworkPolicy:
    def setup_method(self):
        self.np = NetworkPolicy()

    def test_block_private_ip(self):
        assert self.np.check_url("http://127.0.0.1:8080")
        assert self.np.check_url("http://192.168.1.1/admin")
        assert self.np.check_url("http://10.0.0.1")

    def test_allow_public(self):
        assert not self.np.check_url("https://example.com")
        assert not self.np.check_url("https://github.com")


class TestHtmlExtractor:
    def test_extract_title_and_content(self):
        ext = HtmlExtractor()
        html = "<html><head><title>Test</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        result = ext.extract(html, "http://test.com")
        assert result.get("title") == "Test"
        assert "World" in result.get("markdown", "")


class TestDataClasses:
    def test_fetch_result(self):
        fr = FetchResult(url="http://a.com", title="A", markdown="abc",
                        content_length=3, truncated=False)
        assert fr.url == "http://a.com"
        assert fr.markdown == "abc"

    def test_search_result(self):
        sr = SearchResult(position=1, title="T", url="http://a.com", snippet="s")
        assert sr.title == "T"
        assert sr.position == 1


class TestSearchProviderFactory:
    def test_create(self):
        provider = SearchProviderFactory.create()
        if provider:
            assert provider.name


class TestWebFetcher:
    def test_fetch_example(self):
        fetcher = WebFetcher()
        result = fetcher.fetch("https://example.com")
        assert "Example Domain" in result.get("body", "")
        assert result["url"] == "https://example.com"
