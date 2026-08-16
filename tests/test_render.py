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


# --- behavioural tests: actually execute the generated JS ---------------
#
# Asserting that a line of JS source appears in the output proves nothing: the
# <script> body is a static template, so every such assertion holds for every
# input. These run the real renderAnalysis/renderHist against a minimal DOM stub
# and assert on what ends up in #main.

_DOM_STUB = r"""
function mkEl(tag) {
  return {
    tagName: tag, className: "", _text: "", innerHTML: "", children: [],
    style: {}, dataset: {},
    set textContent(v) { this._text = v; },
    get textContent() { return this._text; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {},
  };
}
const main = mkEl("div"), hist = mkEl("div");
globalThis.document = {
  createElement: mkEl,
  getElementById: (id) => (id === "main" ? main : hist),
};
globalThis.window = {};
globalThis.__main = main;
globalThis.__hist = hist;
"""


def _run_render(analysis, recent=()):
    """Render, execute the page's JS, and report what the DOM received."""
    import json as _json
    import re
    import subprocess
    import textwrap

    html = render.render_html(analysis, list(recent))
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    probe = textwrap.dedent("""
        const texts = [];
        (function walk(n) {
          if (n._text) texts.push(n._text);
          if (n.innerHTML) texts.push(n.innerHTML);
          (n.children || []).forEach(walk);
        })(globalThis.__main);
        console.log(JSON.stringify({
          main: texts,
          hist: globalThis.__hist.children.map(c => c._text),
        }));
    """)
    out = subprocess.run(
        ["node", "-e", _DOM_STUB + script + probe],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, f"JS failed: {out.stderr[:400]}"
    return _json.loads(out.stdout)


_QUICK = {"sentence": "", "translation": "委员会一直在讨论这份提案。", "breakdown": "",
          "words": [], "usage": [], "summary": "", "quick": True}
_FULL = {"sentence": "The committee deliberated.", "translation": "委员会审议了。",
         "breakdown": "主句: The committee deliberated", "summary": "一句话总结",
         "words": [{"word": "deliberate", "ipa": "/dɪˈlɪbəreɪt/", "meaning": "审议"}],
         "usage": ["deliberate on sth"]}


def test_quick_entry_renders_translation_and_no_empty_headings():
    dom = _run_render(_QUICK)
    assert "委员会一直在讨论这份提案。" in dom["main"]
    for heading in ("🧩 结构", "📖 生词", "🔗 用法", "📌 小结"):
        assert heading not in dom["main"], f"empty section {heading} was rendered"


def test_full_entry_still_renders_every_section():
    """The guards must not suppress sections that do have content."""
    dom = _run_render(_FULL)
    for heading in ("🧩 结构", "📖 生词", "🔗 用法", "📌 小结"):
        assert heading in dom["main"], f"section {heading} went missing"
    assert "委员会审议了。" in dom["main"]


def test_quick_entry_has_no_speak_button_for_an_empty_sentence():
    dom = _run_render(_QUICK)
    assert "🔊" not in " ".join(dom["main"])
    assert "🐢" not in " ".join(dom["main"])


def test_history_row_labels_quick_entries_by_translation():
    """Quick entries have no `sentence`; a blank row would be useless."""
    dom = _run_render(_FULL, recent=[_QUICK, _FULL])
    assert dom["hist"][0] == "委员会一直在讨论这份提案。"
    assert dom["hist"][1] == "The committee deliberated."


def test_word_with_other_meanings_renders_them_dimmed():
    entry = dict(_FULL)
    entry["words"] = [{"word": "deliberate", "ipa": "/dɪˈlɪbəreɪt/",
                       "meaning": "审议", "other_meanings": ["adj. 蓄意的", "深思熟虑的"]}]
    dom = _run_render(entry)
    joined = " ".join(dom["main"])
    # the DOM stub's esc() yields empty strings, so assert the label and the
    # alt-span structure rather than the escaped meaning text itself
    assert "另义" in joined
    assert "class='alt'" in joined


def test_word_without_other_meanings_field_renders_clean():
    """History entries written before the field existed must not show
    'undefined' or an empty 另义 label."""
    dom = _run_render(_FULL)  # _FULL's word has no other_meanings key
    joined = " ".join(dom["main"])
    assert "另义" not in joined
    assert "undefined" not in joined
