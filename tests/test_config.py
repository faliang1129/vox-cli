"""配置模块测试"""
from paicli.config import VoxCodeConfig, ProviderConfig, pai_config


class TestProviderConfig:
    def test_create(self):
        pc = ProviderConfig(api_key="key", base_url="http://url", model="m")
        assert pc.api_key == "key"
        assert pc.base_url == "http://url"
        assert pc.model == "m"

    def test_get(self):
        pc = ProviderConfig(api_key="key", base_url="http://u", model="m")
        assert pc.get("api_key") == "key"
        assert pc.get("model") == "m"
        assert pc.get("nope", "x") == "x"

    def test_to_dict(self):
        pc = ProviderConfig(api_key="k", base_url="u", model="m")
        d = pc.to_dict()
        assert d["apiKey"] == "k"
        assert d["model"] == "m"

    def test_from_dict(self):
        pc = ProviderConfig.from_dict({"apiKey": "k", "baseUrl": "u", "model": "m"})
        assert pc.api_key == "k"
        assert pc.base_url == "u"


class TestVoxCodeConfig:
    def test_singleton(self):
        assert isinstance(pai_config, VoxCodeConfig)

    def test_default_provider_nonempty(self):
        assert pai_config.default_provider_name


class TestEnvConfig:
    def test_default_provider_env(self, monkeypatch):
        monkeypatch.setenv("VOX_CODE_DEFAULT_PROVIDER", "deepseek")
        cfg = VoxCodeConfig()
        assert cfg.default_provider_name == "deepseek"
