# screen-coach

[English](README.md) | 简体中文

Mac 菜单栏小工具：框选屏幕上的一句英文 → Claude 在悬浮窗里给出拆解
（翻译、句子结构、生词、用法），带发音播放和历史记录。

**先在线试试** → https://screen-coach-trial.defiabell.workers.dev
（免安装免 key：粘贴截图或输入英文，体验额度内免费。）

## 在线体验（网页版）

不用安装任何东西，打开
[screen-coach-trial.defiabell.workers.dev](https://screen-coach-trial.defiabell.workers.dev)
就能直接用，也不需要 API key。四种输入方式：

1. **系统截图 → 粘贴（主路径）**——按 macOS 自带的 ⇧⌃⌘4
   （Shift+Control+Command+4）框选屏幕上的英文，截图自动进剪贴板
   （Windows 用 Win+Shift+S）；切回网页按 ⌘V，立即解析。
   Chrome/Edge/Arc 上更省事：切回页面就自动读取剪贴板，连粘贴都不用按
   （首次授权一次；页面只读图片、从不读剪贴板里的文字）。
2. **拖拽 / 选择图片文件**；
3. **直接输入英文句子**，回车解析。

解析结果与 app 一致：中文翻译＋生词卡（音标、本句义、常见另义），勾选
「完整解析」再加句子结构、用法和小结；生词旁的 🔊 用浏览器语音引擎发音。
图片会先在本地缩到 1600px 再上传，快速模式通常 3 秒左右出结果。

体验额度：每台设备每天 20 次（全站共享每日总预算）。网页版的边界：浏览器
拿不到**全局**快捷键——「在任何应用里一键取词」只有 app 能做到，这也是
值得下载它的理由。

## 两种取词方式

- **常驻取词框** —— 在你常读英文的区域（字幕、文档栏）留一个细边框，
  每次分析框内的内容。边框是点击穿透的，不挡下面的应用。
  菜单 → `Adjust Region…` 可拖动和缩放，按 Esc 完成。
- **拖选** —— 像截图一样用十字线临时框选一块区域。

## 三种触发方式

- **悬浮 📖 球** —— 可拖动、永远置顶、记住位置。左键按 `Use Region`
  当前模式执行分析，右键弹出与菜单栏相同的菜单。它存在的原因：菜单栏
  图标跟着系统菜单栏走，外接显示器时可能落在你没在看的屏幕上，这时
  就没东西可点了；悬浮球固定在内建屏幕上。
- **菜单栏** —— `Analyze Region` 和 `Analyze Selection` 两个入口始终可用，
  不受模式切换影响。
- **⇧⌘E 全局快捷键** —— 触发拖选。需要辅助功能权限；其他功能不需要。
  可改键：菜单 → `Set Hotkey…` 弹出小窗，按下新组合键即生效
  （必须含 ⌘/⌥/⌃，Esc 取消），无需重启。菜单项标题实时显示当前键位。

菜单里的 `Use Region` 是**模式开关**而非显示开关：勾选＝悬浮球左键分析
常驻取词框（并显示边框让你看到范围），不勾选＝左键拖选。

发音永不自动播放：点 🔊（常速）或 🐢（慢速）朗读整句或单词。

分析结果追加保存在 `~/Library/Application Support/Screen Coach/history.jsonl`，
悬浮窗列出最近 20 条，点击可重新查看。

## 系统要求

- **macOS**：在 macOS 15（Apple Silicon）上开发并实测；更早版本（约 12+）
  理论可用但未逐版本验证。Intel 机器需自行构建。
- **不需要任何浏览器**：悬浮窗由 macOS 自带的 WebKit（WKWebView，经
  pywebview）渲染，与你装没装 Chrome/Safari 的版本无关。
- **自行构建**需要 Python 3.9+（系统自带的 `python3` 即可）。

## 构建与安装

首次准备（已有 `.venv` 可跳过）：

    cd personal-projects/english-learning/screen-coach
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

然后构建并安装：

    ./build_app.sh

这会构建 `Screen Coach.app`、用固定证书签名（原因见下方
[权限](#权限macos)）、用 `rsync` 装进 /Applications 并启动。之后像普通
app 一样从 Spotlight、启动台或 /Applications 打开即可。

首次启动：
1. 菜单栏出现 📖 图标和悬浮球。**试用不需要 API key**：没有设置 key 时，
   请求会经过一个小型体验代理（`trial-worker/`，作者的 key 托管在
   Cloudflare Worker 上），有每日限额——每台设备、每个 IP、以及全局总预算。
   额度用完，或任何时候想不限量直连官方，用菜单 → `Set API Key…` 填入
   你自己的 Anthropic key。key 存进 macOS 钥匙串
   （service `com.jinkun.screen-coach`），不落文件，只需输入一次。
2. 第一次触发分析时 macOS 会请求「屏幕录制」权限，授权后退出重开 app。
3. 想用 ⇧⌘E 快捷键就按提示授予「辅助功能」权限；只用悬浮球和菜单可跳过。
4. 可选：菜单里勾上 `Launch at Login` 开机自启。

改完代码重新跑 `./build_app.sh` 即可，权限在重建后依然有效——为什么这
不是理所当然的，见下方说明。

## 测试

    .venv/bin/python -m pytest tests/ -q

全部测试不需要 GUI 和 API key：几何计算、坐标转换、截图顺序、钥匙串
超时、模式分发都以纯逻辑覆盖。窗口渲染和真实鼠标拖拽靠手工验证。

## 权限（macOS）

- **屏幕录制** —— `screencapture` 需要。首次提示时授予
  （系统设置 → 隐私与安全性 → 屏幕录制）。
- **辅助功能** —— 仅 ⇧⌘E 快捷键需要。悬浮球、右键菜单、菜单栏都不依赖它。
  如果授权后快捷键仍无效，把 Screen Coach 从辅助功能列表里**整条删除**，
  让 app 下次启动时重新添加——失效的旧条目会显示为已启用，但
  `CGEventTapCreate` 依然返回 NULL。
- **重建说明** —— `build_app.sh` 用固定的自签名证书签名（默认取钥匙串里
  第一个代码签名身份，可用 `SIGN_IDENTITY=<名称>` 覆盖），并用 `rsync`
  而非删除重拷来安装。两者都重要：ad-hoc 签名每次构建哈希都变，删除重拷
  会换 inode，任何一种都会让 macOS 当成另一个 app——辅助功能开关看着是
  开的而 `AXIsProcessTrusted()` 返回 False，钥匙串条目的 ACL 也会失配
  （曾导致启动时假死）。
- **自动化（System Events）** —— `Launch at Login` 开关需要。报错时去
  系统设置 → 隐私与安全性 → 自动化 → Screen Coach → System Events 授权。

## 代码布局

| 文件 | 职责 |
|---|---|
| `app.py` | 菜单、触发入口、共享的分析管线 |
| `region.py` | 常驻取词框：几何、窗口、自己的截图 |
| `floatball.py` | 可拖动悬浮球及其右键菜单 |
| `capture.py` | `screencapture` 封装（交互式和固定矩形） |
| `analyzer.py` | prompt 与结构化输出 schema |
| `render.py` | 拆解结果的 HTML |
| `viewer.py` | 悬浮窗（独立进程；基于 `say` 的朗读） |
| `keychain.py` / `config.py` | API key 的存取与解析 |
| `trial-worker/` | 免 key 体验代理（Cloudflare Worker） |

`region.py` 刻意不知道 `analyzer`/`render`/API 的存在——它只处理几何和
像素，这正是它不需要 GUI、权限、key 就能测试的原因。拿图之后做什么由
`app.py` 决定。

## 容易踩的坑

都是实测踩出来的，不是推理出来的：

- **AppKit 和 `screencapture` 的 y 轴方向相反。** AppKit 从内建屏幕左下角
  向上量，`screencapture -R` 从左上角向下量。`region.to_capture_rect()`
  负责转换，有测试钉住了对过真实像素的用例。
- **`NSScreen.screens()[0]` 不是内建屏幕**，而是拥有菜单栏的那块屏。
  凡是「放在用户看得见的地方」的逻辑，都要找 frame 原点为 `(0, 0)` 的屏幕。
- **`orderOut_` 不代表屏幕已重绘。** 隐藏边框后立即截图会拍到自己的边框，
  `region.capture()` 会等一帧。
- **主线程上的阻塞 I/O 会让这个 app 无声死掉。** 一次无界的钥匙串读取曾
  让它在菜单栏出现前就冻住，看起来就是没启动。现在钥匙串读写都有超时，
  `screencapture` 有超时，API key 弹窗也放在菜单就绪之后。
- **被动的 `NSEvent` 全局监听永远收不到 ⌘ 组合键。** 换了三种修饰键组合
  才发现是机制本身不对；快捷键用的是主 run loop 上的 `CGEventTap`。
- **py2app 包里 `Path(__file__).parent` 可能在 zip 里。** 用户数据要放
  `~/Library/Application Support/`，不能放代码旁边。
- **pyobjc 子类要用 `objc.super(...)`**；对 AppKit 类方法做
  `monkeypatch.setattr` 会被静默忽略——要 patch 模块属性。

## 其他说明

- API key 存 macOS 钥匙串（service `com.jinkun.screen-coach`），永不落
  文件或环境变量。`_get_client()` 固定 `base_url`，指向内部网关的 shell
  环境变量无法悄悄劫持它。
- 完整分析用 `config.MODEL`（`claude-sonnet-5`），快速翻译用 Haiku。实测
  同一句话：sonnet-5 约 3 秒；`effort` 参数反而更慢还被部分模型拒绝，
  所以没有用。
- 运行时状态（`history.jsonl`、`region.json`、`ball.json`、`prefs.json`）
  在 `~/Library/Application Support/Screen Coach/`；调试日志在
  `~/Library/Logs/screen-coach-debug.log`。

## 体验代理（想自己部署的话）

`trial-worker/` 是一个 Cloudflare Worker，让没有 key 的安装开箱即用
（用部署者的 key），带限额（设备 20 次/天、IP 40 次/天、全局 $1/天——
常量都在 `src/index.js`）。自己部署：

    cd trial-worker
    wrangler kv namespace create TRIAL_KV     # 把返回的 id 填进 wrangler.jsonc
    wrangler deploy
    wrangler secret put ANTHROPIC_API_KEY     # 粘贴你的 key

然后把 `config.py` 里的 `TRIAL_BASE_URL` 指向你的 Worker 地址。
GET Worker 首页可看当日总消耗。
