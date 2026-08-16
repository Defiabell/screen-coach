"""Render an analysis + recent history into one self-contained HTML page."""
from __future__ import annotations

import json

import config

_PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font: 15px/1.6 -apple-system, sans-serif; margin: 0; background:#1e1e1e; color:#eee; }}
  .wrap {{ display:flex; height:100vh; }}
  .main {{ flex:1; padding:18px 20px; overflow:auto; }}
  .side {{ width:150px; border-left:1px solid #333; padding:10px; overflow:auto; background:#191919; }}
  .side h4 {{ margin:4px 0 8px; color:#888; font-size:12px; }}
  .hist {{ padding:6px 4px; border-bottom:1px solid #2a2a2a; cursor:pointer; font-size:12px; color:#bbb; }}
  .hist:hover {{ color:#fff; }}
  .sentence {{ font-size:1.1em; }}
  .zh {{ color:#8fd; margin:6px 0 14px; }}
  .label {{ color:#e0a; font-weight:bold; margin-top:12px; }}
  .word {{ margin:3px 0; }}
  .ipa {{ color:#3a9d7f; }}
  .alt {{ color:#8a8a8a; font-size:12px; }}
  button.spk {{ background:#333; color:#fff; border:none; border-radius:4px; cursor:pointer; margin-left:6px; }}
</style></head>
<body><div class="wrap">
  <div class="main" id="main"></div>
  <div class="side"><h4>历史</h4><div id="hist"></div></div>
</div>
<script>
const ANALYSIS = {analysis_json};
const RECENT = {recent_json};
const WPM = {wpm};
const WPM_SLOW = {wpm_slow};

// TTS via macOS `say` through the pywebview bridge (window.pywebview.api.speak),
// NOT the webview Web Speech API — WKWebView doesn't reliably expose installed
// Premium voices. wpm passed per call (WPM normal, WPM_SLOW for 🐢).
function speak(text, wpm) {{
  if (!text || !(window.pywebview && window.pywebview.api)) return;
  window.pywebview.api.speak(text, wpm || WPM);
}}
function spk(text, slow) {{
  const b = document.createElement("button");
  b.className = "spk"; b.textContent = slow ? "🐢" : "🔊";
  b.onclick = () => speak(text, slow ? WPM_SLOW : WPM);
  return b;
}}
// render only — speaking is always user-initiated (🔊 / 🐢), never automatic
function show(a) {{ renderAnalysis(a); }}
function esc(s) {{ const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }}

function renderAnalysis(a) {{
  const m = document.getElementById("main");
  m.innerHTML = "";
  const sent = document.createElement("div");
  sent.className = "sentence";
  // Quick-translate entries carry only a translation, so every section below is
  // rendered only when it actually has content — otherwise the window would show
  // four bare headings under the Chinese line.
  if (a.sentence) {{
    sent.innerHTML = esc(a.sentence);
    sent.appendChild(spk(a.sentence)); sent.appendChild(spk(a.sentence, true));
    m.appendChild(sent);
  }}
  const zh = document.createElement("div"); zh.className = "zh"; zh.textContent = a.translation || ""; m.appendChild(zh);
  const add = (label, node) => {{ const h = document.createElement("div"); h.className="label"; h.textContent=label; m.appendChild(h); m.appendChild(node); }};
  if (a.breakdown) {{
    const bd = document.createElement("div"); bd.textContent = a.breakdown; add("🧩 结构", bd);
  }}
  if ((a.words || []).length) {{
    const wl = document.createElement("div");
    a.words.forEach(w => {{
      const row = document.createElement("div"); row.className = "word";
      const alts = (w.other_meanings || []);
      row.innerHTML = "<b>" + esc(w.word) + "</b> <span class='ipa'>" + esc(w.ipa) + "</span> — " + esc(w.meaning)
        + (alts.length ? " <span class='alt'>另义：" + alts.map(esc).join("；") + "</span>" : "");
      row.appendChild(spk(w.word));
      wl.appendChild(row);
    }});
    add("📖 生词", wl);
  }}
  if ((a.usage || []).length) {{
    const us = document.createElement("ul");
    a.usage.forEach(u => {{ const li = document.createElement("li"); li.textContent = u; us.appendChild(li); }});
    add("🔗 用法", us);
  }}
  if (a.summary) {{
    const sm = document.createElement("div"); sm.textContent = a.summary; add("📌 小结", sm);
  }}
}}

function renderHist() {{
  const h = document.getElementById("hist");
  RECENT.forEach(item => {{
    const d = document.createElement("div"); d.className = "hist";
    // Quick-translate entries have no `sentence`; fall back to the translation
    // so they don't show up as blank rows.
    d.textContent = (item.sentence || item.translation || "").slice(0, 40);
    d.onclick = () => show(item);
    h.appendChild(d);
  }});
}}
renderAnalysis(ANALYSIS); renderHist();
</script></body></html>
"""


def _safe_json(obj) -> str:
    """JSON for embedding inside <script>. Escape <, >, & so a captured
    sentence containing e.g. '</script>' can't break out of the block."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render_html(analysis: dict, recent: list[dict]) -> str:
    return _PAGE.format(
        analysis_json=_safe_json(analysis),
        recent_json=_safe_json(recent),
        wpm=config.SPEAK_WPM,
        wpm_slow=config.SPEAK_WPM_SLOW,
    )
