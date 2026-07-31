import base64
import capture
import pytest
import subprocess


def test_capture_region_returns_none_when_no_file(monkeypatch, tmp_path):
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))
    # runner does nothing -> no file created -> user cancelled
    result = capture.capture_region(runner=lambda *a, **k: None)
    assert result is None


def test_capture_region_returns_path_when_file_created(monkeypatch, tmp_path):
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))

    def fake_runner(cmd, **k):
        target.write_bytes(b"\x89PNG")  # simulate screencapture writing a file

    result = capture.capture_region(runner=fake_runner)
    assert result == str(target)


def test_to_base64_roundtrip(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG")
    assert base64.b64decode(capture.to_base64(str(p))) == b"\x89PNG"


def test_capture_rect_builds_R_argument(monkeypatch, tmp_path):
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))
    seen = {}

    def fake_runner(cmd, **k):
        seen["cmd"] = cmd
        seen["timeout"] = k.get("timeout")
        target.write_bytes(b"\x89PNG")

    result = capture.capture_rect(10.0, 20.0, 300.0, 100.0, runner=fake_runner)
    assert result == str(target)
    # -R 参数按 x,y,w,h 传入（调用方已完成坐标系换算）
    assert "-R" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("-R") + 1] == "10,20,300,100"
    assert seen["timeout"] == capture.CAPTURE_TIMEOUT


def test_capture_rect_raises_when_no_file(monkeypatch, tmp_path):
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))
    # runner 什么都不做 → 没文件 → 定坐标截图没有「取消」语义，必须报错
    with pytest.raises(capture.CaptureError):
        capture.capture_rect(0.0, 0.0, 100.0, 100.0, runner=lambda *a, **k: None)


def test_capture_rect_raises_on_timeout(monkeypatch, tmp_path):
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))

    def slow_runner(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, k.get("timeout", 0))

    with pytest.raises(capture.CaptureError) as ei:
        capture.capture_rect(0.0, 0.0, 100.0, 100.0, runner=slow_runner)
    assert "超时" in str(ei.value) or "timed out" in str(ei.value).lower()


def test_capture_region_also_has_timeout(monkeypatch, tmp_path):
    """交互拖选同样不能无限期挂住 worker 线程。"""
    target = tmp_path / "shot.png"
    monkeypatch.setattr(capture, "_tmp_png", lambda: str(target))
    seen = {}

    def fake_runner(cmd, **k):
        seen["timeout"] = k.get("timeout")

    capture.capture_region(runner=fake_runner)
    assert seen["timeout"] is not None
