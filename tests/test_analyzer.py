import json

import analyzer
import config


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.last_kwargs = None

        class _Messages:
            def create(inner, **kwargs):
                self.last_kwargs = kwargs
                return _Resp(json.dumps(self._payload))

        self.messages = _Messages()


def test_analyze_image_parses_and_sends_image():
    payload = {
        "sentence": "The build failed.",
        "translation": "构建失败了。",
        "breakdown": "The build(主) + failed(谓)。",
        "words": [{"word": "build", "ipa": "/bɪld/", "meaning": "构建"}],
        "usage": ["the build failed = 构建挂了"],
        "summary": "一句话：构建失败。",
    }
    client = _FakeClient(payload)

    result = analyzer.analyze_image(client, "ZmFrZQ==")

    assert result["translation"] == "构建失败了。"
    assert result["words"][0]["word"] == "build"
    # image block is sent, before the text block
    content = client.last_kwargs["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["data"] == "ZmFrZQ=="
    # structured output requested
    assert client.last_kwargs["output_config"]["format"]["type"] == "json_schema"


def test_translate_image_shape_matches_analyze(monkeypatch):
    """The fast path must return the same shape, so nothing downstream forks."""
    import json as _json

    payload = {
        "translation": "  委员会一直在讨论这份提案。  ",
        "words": [{"word": "deliberate", "ipa": "/dɪˈlɪbəreɪt/",
                   "meaning": "讨论；审议", "other_meanings": ["adj. 蓄意的"]}],
    }

    class FakeBlock:
        type = "text"
        text = _json.dumps(payload)

    class FakeResp:
        content = [FakeBlock()]

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                # words now ride along, so quick mode uses structured output too
                assert kw["output_config"]["format"]["type"] == "json_schema"
                assert kw["model"] == config.QUICK_MODEL
                assert kw["max_tokens"] == config.QUICK_MAX_TOKENS
                return FakeResp()

    out = analyzer.translate_image(FakeClient(), "Zm9v")
    assert out["translation"] == "委员会一直在讨论这份提案。"   # stripped
    assert out["quick"] is True
    assert set(out) >= {"sentence", "translation", "breakdown", "words", "usage", "summary"}
    assert out["words"][0]["other_meanings"] == ["adj. 蓄意的"]
    assert out["usage"] == []


def test_translate_image_falls_back_when_model_returns_nothing():
    class FakeResp:
        content = []

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                return FakeResp()

    out = analyzer.translate_image(FakeClient(), "Zm9v")
    assert out["translation"] == "未识别到英文"
    assert out["words"] == []


def test_word_schemas_carry_other_meanings():
    """Both modes must ask for other common meanings of polysemous words."""
    full_word = analyzer.ANALYSIS_SCHEMA["properties"]["words"]["items"]
    assert "other_meanings" in full_word["properties"]
    assert "other_meanings" in full_word["required"]
    quick_word = analyzer.QUICK_SCHEMA["properties"]["words"]["items"]
    assert "other_meanings" in quick_word["properties"]
    assert "other_meanings" in quick_word["required"]
    # quick mode keeps its latency budget by capping the word list
    assert "5" in analyzer.TRANSLATE_PROMPT
    assert "other_meanings" in analyzer.SYSTEM_PROMPT
