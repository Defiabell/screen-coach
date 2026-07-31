"""py2app build config for Screen Coach.

Build:
    .venv/bin/pip install py2app
    .venv/bin/python setup.py py2app          # full, distributable bundle -> dist/Screen Coach.app
    .venv/bin/python setup.py py2app -A       # alias (dev) build: fast, references live files

The bundle is a single binary that dispatches on argv: normal launch runs the
menu-bar app; `--viewer <html>` (re-exec'd by app.py) shows the floating window.
"""
from setuptools import setup

APP = ["app.py"]
OPTIONS = {
    "argv_emulation": False,  # True uses Carbon (broken on modern macOS) and mangles our argv
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "Screen Coach",
        "CFBundleDisplayName": "Screen Coach",
        "CFBundleIdentifier": "com.jinkun.screen-coach",
        "CFBundleShortVersionString": "1.1.0",
        "CFBundleVersion": "1.1.0",
        "LSUIElement": True,  # menu-bar accessory: no Dock icon
        "NSHighResolutionCapable": True,
    },
    # Follow imports where possible, but name the compiled/dynamic ones explicitly.
    "packages": [
        "anthropic",
        "rumps",
        "webview",
        "httpx",
        "httpcore",
        "certifi",
        "pydantic",
        "pydantic_core",
        "anyio",
        "sniffio",
        "jiter",
        "distro",
        "h11",
        "idna",
    ],
    "includes": ["objc", "Foundation", "AppKit", "WebKit", "Quartz", "ApplicationServices"],
}

setup(
    name="Screen Coach",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
