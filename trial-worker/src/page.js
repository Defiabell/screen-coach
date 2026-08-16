/**
 * The try-it-online page served at GET /. Lets a visitor paste a screenshot
 * (⌘V / drag-drop / file picker) or type an English sentence, and runs the
 * same analysis the app does, through the same trial-quota proxy.
 *
 * The prompts/schemas here mirror analyzer.py — the app is the source of
 * truth; keep them in sync when the Python side changes.
 */

export function renderPage({ date, spentUsd, budgetUsd }) {
  return `<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>screen-coach 在线试用</title>
<style>
  body { font-family: system-ui; max-width: 42em; margin: 4vh auto; padding: 0 1em; line-height: 1.7; color: #222; }
  h1 { font-size: 1.35em; }
  .drop { border: 2px dashed #bbb; border-radius: 10px; padding: 1.2em; text-align: center; color: #888; cursor: pointer; }
  .drop.hover { border-color: #2a7; color: #2a7; }
  .drop img { max-width: 100%; max-height: 220px; border-radius: 6px; }
  textarea { width: 100%; box-sizing: border-box; min-height: 3.2em; font: inherit; padding: 0.5em; border: 1px solid #ccc; border-radius: 8px; }
  button { font: inherit; padding: 0.45em 1.4em; border: 0; border-radius: 8px; background: #2a7; color: #fff; cursor: pointer; }
  button:disabled { background: #aaa; }
  label { font-size: 0.92em; color: #555; }
  #result { margin-top: 1.2em; }
  .zh { font-size: 1.12em; font-weight: 600; margin: 0.4em 0; }
  .label { color: #888; font-size: 0.85em; margin-top: 0.9em; }
  .word { margin: 3px 0; }
  .ipa { color: #3a9d7f; }
  .alt { color: #8a8a8a; font-size: 0.9em; }
  .spk { cursor: pointer; text-decoration: none; margin-left: 0.3em; }
  .err { color: #b33; background: #fdf0f0; border-radius: 8px; padding: 0.7em 1em; }
  footer { margin-top: 3em; color: #999; font-size: 0.85em; border-top: 1px solid #eee; padding-top: 1em; }
</style>
<body>
<h1>📖 screen-coach 在线试用</h1>
<p>框选屏幕即时解析英文的 Mac 菜单栏工具。完整体验（真·全局快捷键、常驻取词框）请
<a href="https://github.com/Defiabell/screen-coach">下载 app</a>；网页版这样用：</p>

<ol style="background:#f6f8f7;border-radius:10px;padding:0.9em 1.2em 0.9em 2.4em;margin:0.8em 0">
  <li>按 <b>⇧⌃⌘4</b> 框选屏幕上的英文（Windows：<b>Win+Shift+S</b>），截图自动进剪贴板；</li>
  <li>切回本页 —— <b>自动读取剪贴板并解析</b>（首次浏览器会请求剪贴板权限；没弹或用 Safari 就按 <b>⌘V</b>）；</li>
  <li>秒出翻译和生词卡。</li>
</ol>

<div class="drop" id="drop">或：⌘V 粘贴 / 拖拽图片到这里 / 点击选择文件</div>
<p style="text-align:center;margin:0.4em 0">
  <button id="shot" type="button" style="background:#aaa;font-size:0.85em;padding:0.3em 0.9em">备用：页面内截屏</button>
</p>
<input type="file" id="file" accept="image/*" hidden>
<div id="cropWrap" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9;cursor:crosshair;overflow:auto;text-align:center">
  <p style="color:#fff;margin:0.6em">在截图上拖拽框选要解析的区域（Esc 取消）</p>
  <div style="position:relative;display:inline-block">
    <canvas id="cropCanvas" style="max-width:96vw;display:block"></canvas>
    <div id="cropBox" style="position:absolute;border:2px solid #2a7;background:rgba(42,170,119,.15);display:none"></div>
  </div>
</div>
<p style="text-align:center;color:#aaa;margin:0.5em 0">—— 或 ——</p>
<textarea id="text" placeholder="输入或粘贴一句英文，例如：The committee deliberated the proposal."></textarea>
<p>
  <button id="go">解析</button>
  <label style="margin-left:1em"><input type="checkbox" id="full"> 完整解析（句子结构＋用法，稍慢）</label>
</p>
<div id="result"></div>

<footer>体验额度：每设备每天 20 次 · 全站今日已用 $${spentUsd} / $${budgetUsd}（${date} UTC）· 额度用完可在 app 中填入自己的 API key ·
<a href="https://github.com/Defiabell/screen-coach">GitHub</a></footer>

<script>
"use strict";
var img64 = null;

var device = localStorage.getItem("sc-device");
if (!device) { device = crypto.randomUUID(); localStorage.setItem("sc-device", device); }

var drop = document.getElementById("drop");
var fileInput = document.getElementById("file");
var textEl = document.getElementById("text");
var goBtn = document.getElementById("go");
var result = document.getElementById("result");

drop.addEventListener("click", function () { fileInput.click(); });
fileInput.addEventListener("change", function () { if (fileInput.files[0]) loadImage(fileInput.files[0]); });
document.addEventListener("paste", function (e) {
  var items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  for (var i = 0; i < items.length; i++) {
    if (items[i].type.indexOf("image/") === 0) { loadImage(items[i].getAsFile()); e.preventDefault(); return; }
  }
});

// The hero flow: screenshot with the OS hotkey, switch back to this tab, and
// the page pulls the image straight off the clipboard — no ⌘V needed.
// Reads IMAGES only (never clipboard text — that could be anything private).
// Safari blocks clipboard.read() outside a user gesture; the catch below
// degrades silently and ⌘V remains the fallback.
var lastClipSize = 0;
function tryClipboard() {
  if (!(navigator.clipboard && navigator.clipboard.read) || goBtn.disabled) return;
  navigator.clipboard.read().then(function (items) {
    for (var i = 0; i < items.length; i++) {
      var type = items[i].types.filter(function (t) { return t.indexOf("image/") === 0; })[0];
      if (type) {
        return items[i].getType(type).then(function (blob) {
          if (blob.size === lastClipSize) return; // same screenshot as last focus
          lastClipSize = blob.size;
          loadImage(blob);
        });
      }
    }
  }).catch(function () { /* no permission / Safari: paste still works */ });
}
window.addEventListener("focus", tryClipboard);

// In-page screen grab: getDisplayMedia one frame → drag-select crop → analyze.
var shotBtn = document.getElementById("shot");
if (!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia)) shotBtn.style.display = "none";
shotBtn.addEventListener("click", function () {
  navigator.mediaDevices.getDisplayMedia({ video: true, audio: false }).then(function (stream) {
    var video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    video.play();
    video.addEventListener("loadeddata", function () {
      setTimeout(function () {
        var c = document.getElementById("cropCanvas");
        c.width = video.videoWidth;
        c.height = video.videoHeight;
        c.getContext("2d").drawImage(video, 0, 0);
        stream.getTracks().forEach(function (t) { t.stop(); });
        openCrop();
      }, 200); // let the first real frame land
    });
  }).catch(function () { /* user cancelled the share dialog */ });
});

var cropWrap = document.getElementById("cropWrap");
var cropBox = document.getElementById("cropBox");
function openCrop() {
  cropWrap.style.display = "block";
  cropBox.style.display = "none";
  var c = document.getElementById("cropCanvas");
  var start = null;
  function pos(e) {
    var r = c.getBoundingClientRect();
    return { x: Math.min(Math.max(e.clientX - r.left, 0), r.width), y: Math.min(Math.max(e.clientY - r.top, 0), r.height), r: r };
  }
  c.onmousedown = function (e) { start = pos(e); e.preventDefault(); };
  c.onmousemove = function (e) {
    if (!start) return;
    var p = pos(e);
    cropBox.style.display = "block";
    cropBox.style.left = Math.min(start.x, p.x) + "px";
    cropBox.style.top = Math.min(start.y, p.y) + "px";
    cropBox.style.width = Math.abs(p.x - start.x) + "px";
    cropBox.style.height = Math.abs(p.y - start.y) + "px";
  };
  c.onmouseup = function (e) {
    if (!start) return;
    var p = pos(e);
    var scale = c.width / p.r.width; // displayed px → canvas px
    var x = Math.min(start.x, p.x) * scale, y = Math.min(start.y, p.y) * scale;
    var w = Math.abs(p.x - start.x) * scale, h = Math.abs(p.y - start.y) * scale;
    start = null;
    closeCrop();
    if (w < 8 || h < 8) return; // a click, not a selection
    var out = document.createElement("canvas");
    out.width = w; out.height = h;
    out.getContext("2d").drawImage(c, x, y, w, h, 0, 0, w, h);
    out.toBlob(function (blob) { loadImage(blob); }, "image/png");
  };
  document.addEventListener("keydown", escCrop);
}
function escCrop(e) { if (e.key === "Escape") closeCrop(); }
function closeCrop() { cropWrap.style.display = "none"; document.removeEventListener("keydown", escCrop); }
["dragover", "dragleave", "drop"].forEach(function (ev) {
  drop.addEventListener(ev, function (e) {
    e.preventDefault();
    drop.classList.toggle("hover", ev === "dragover");
    if (ev === "drop" && e.dataTransfer.files[0]) loadImage(e.dataTransfer.files[0]);
  });
});

function loadImage(file) {
  var img = new Image();
  img.onload = function () {
    // Downscale: keeps requests cheap and under the proxy's size cap.
    var scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    var dataUrl = canvas.toDataURL("image/png");
    img64 = dataUrl.split(",")[1];
    drop.innerHTML = "";
    var preview = new Image();
    preview.src = dataUrl;
    drop.appendChild(preview);
    textEl.value = "";
    URL.revokeObjectURL(img.src);
    analyze(); // screenshot in → translation out, no extra click
  };
  img.src = URL.createObjectURL(file);
}

textEl.addEventListener("input", function () {
  if (textEl.value.trim()) { img64 = null; drop.innerHTML = "点击选择图片，或直接 ⌘V 粘贴截图 / 拖拽到这里"; }
});

// Prompts/schemas mirror analyzer.py (quick + full modes).
var WORD_ITEM = { type: "object", properties: { word: { type: "string" }, ipa: { type: "string" }, meaning: { type: "string" }, other_meanings: { type: "array", items: { type: "string" } } }, required: ["word", "ipa", "meaning", "other_meanings"], additionalProperties: false };
var QUICK_SCHEMA = { type: "object", properties: { translation: { type: "string" }, words: { type: "array", items: WORD_ITEM } }, required: ["translation", "words"], additionalProperties: false };
var FULL_SCHEMA = { type: "object", properties: { sentence: { type: "string" }, translation: { type: "string" }, breakdown: { type: "string" }, words: { type: "array", items: WORD_ITEM }, usage: { type: "array", items: { type: "string" } }, summary: { type: "string" } }, required: ["sentence", "translation", "breakdown", "words", "usage", "summary"], additionalProperties: false };
var QUICK_PROMPT = "You translate English into Simplified Chinese for a native speaker whose vocabulary is about 2300 words. Read the given English (in the image or the text). Set 'translation' to ONLY the translation - no notes, no pinyin, no quotes. 'words' lists at most 5 genuinely harder words; for each give the IPA, the meaning IN THIS sentence in Simplified Chinese (a few characters, not a definition sentence), and other_meanings: up to 2 OTHER common meanings, also in Simplified Chinese with the part of speech marked, when the word genuinely has them - an empty array otherwise. If there is no readable English, set translation to 未识别到英文 and words to [].";
var FULL_PROMPT = "You are an English reading tutor for a Chinese native speaker whose vocabulary is about 2300 words. Read the given English (in the image or the text) and produce a learning breakdown via the structured output only. Rules: write translation and every explanation in Simplified Chinese, using short sentences, one point per line. 'breakdown' marks the main clause and any subordinate or non-finite clauses. 'words' lists only the harder words (at most 8); for each give the IPA, the meaning IN THIS sentence, and other_meanings: up to 3 OTHER common meanings (with the part of speech marked) when the word genuinely has them - an empty array otherwise. 'usage' gives one or two collocation or sentence-pattern points worth learning. 'summary' is one line. If there is no readable English, set translation to 未识别到英文 and leave the other fields empty.";

goBtn.addEventListener("click", analyze);
textEl.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); analyze(); }
});

function analyze() {
  var text = textEl.value.trim();
  if (!img64 && !text) { showErr("先粘贴一张截图，或输入一句英文。"); return; }
  var full = document.getElementById("full").checked;
  var content = [];
  if (img64) content.push({ type: "image", source: { type: "base64", media_type: "image/png", data: img64 } });
  content.push({ type: "text", text: img64 ? "Analyze the English in this image." : "Analyze this English: " + text });
  var body = {
    model: full ? "claude-sonnet-5" : "claude-haiku-4-5-20251001",
    max_tokens: full ? 4096 : 1024,
    system: full ? FULL_PROMPT : QUICK_PROMPT,
    output_config: { format: { type: "json_schema", schema: full ? FULL_SCHEMA : QUICK_SCHEMA } },
    messages: [{ role: "user", content: content }],
  };
  goBtn.disabled = true;
  goBtn.textContent = "解析中…";
  result.innerHTML = "";
  fetch("/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-trial-device": device },
    body: JSON.stringify(body),
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.type === "error") { showErr(d.error.message); return; }
    var textBlock = (d.content || []).filter(function (b) { return b.type === "text"; })[0];
    render(JSON.parse(textBlock.text));
  }).catch(function (e) { showErr("请求失败：" + e); }).finally(function () {
    goBtn.disabled = false;
    goBtn.textContent = "解析";
  });
}

function el(tag, cls, textContent) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (textContent) n.textContent = textContent;
  return n;
}

function speaker(word, slow) {
  var a = el("a", "spk", slow ? "🐢" : "🔊");
  a.href = "javascript:void 0";
  a.onclick = function () {
    var u = new SpeechSynthesisUtterance(word);
    u.lang = "en-US";
    u.rate = slow ? 0.6 : 0.95;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  };
  return a;
}

function render(a) {
  result.innerHTML = "";
  if (a.sentence) {
    var s = el("div", null, a.sentence);
    s.appendChild(speaker(a.sentence));
    s.appendChild(speaker(a.sentence, true));
    result.appendChild(s);
  }
  result.appendChild(el("div", "zh", a.translation || ""));
  if (a.breakdown) { result.appendChild(el("div", "label", "🧩 结构")); result.appendChild(el("div", null, a.breakdown)); }
  if ((a.words || []).length) {
    result.appendChild(el("div", "label", "📖 生词"));
    a.words.forEach(function (w) {
      var row = el("div", "word");
      var b = el("b", null, w.word);
      row.appendChild(b);
      row.appendChild(document.createTextNode(" "));
      row.appendChild(el("span", "ipa", w.ipa));
      row.appendChild(document.createTextNode(" — " + w.meaning + " "));
      var alts = w.other_meanings || [];
      if (alts.length) row.appendChild(el("span", "alt", "另义：" + alts.join("；")));
      row.appendChild(speaker(w.word));
      result.appendChild(row);
    });
  }
  if ((a.usage || []).length) {
    result.appendChild(el("div", "label", "🔗 用法"));
    var ul = document.createElement("ul");
    a.usage.forEach(function (u) { ul.appendChild(el("li", null, u)); });
    result.appendChild(ul);
  }
  if (a.summary) { result.appendChild(el("div", "label", "📌 小结")); result.appendChild(el("div", null, a.summary)); }
}

function showErr(msg) {
  result.innerHTML = "";
  result.appendChild(el("div", "err", msg));
}
</script>
</body>
</html>`;
}
