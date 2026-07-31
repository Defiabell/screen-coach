import json
import render


def test_render_html_embeds_and_escapes():
    analysis = {
        "sentence": "The <build> failed.",
        "translation": "构建失败了。",
        "breakdown": "The build(主) + failed(谓)。",
        "words": [{"word": "build", "ipa": "/bɪld/", "meaning": "构建"}],
        "usage": ["the build failed"],
        "summary": "一句话：构建失败。",
    }
    out = render.render_html(analysis, recent=[analysis])

    assert "<!doctype html>" in out.lower()
    assert "pywebview.api.speak" in out       # TTS wired via the say bridge
    assert "构建失败了。" in out              # translation present
    # raw angle brackets from the sentence must be embedded as escaped JSON, not literal tags
    assert "<build>" not in out
    assert "speak(" in out                    # play button hook


def test_html_has_no_autospeak_on_load():
    """弹窗不应自动朗读——只有点 🔊/🐢 才发声。"""
    a = {"sentence": "Hello there.", "translation": "你好。", "breakdown": "",
         "words": [], "usage": [], "summary": ""}
    html = render.render_html(a, [])
    # 初次加载路径不得调用 speak
    assert "pywebviewready" not in html
    # 历史点击路径也不得自动朗读
    assert "if (a.sentence) speak(a.sentence)" not in html
    # 但按钮的 onclick 必须还在
    assert "b.onclick = () => speak(text" in html
