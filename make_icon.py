"""One-off generator for icon.icns (a 📖 rendered at each size iconutil wants).
Run manually when the icon needs to change: `.venv/bin/python make_icon.py`.
Not part of the build pipeline — the output is committed to the repo."""
import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSAttributedString,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSFont,
    NSGraphicsContext,
    NSPNGFileType,
)

EMOJI = "📖"
HERE = Path(__file__).parent
# (pixel size, iconset filename) — iconutil's required naming convention
SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def render_emoji_png(emoji: str, size: int, out_path: Path) -> None:
    # Draw into an explicitly-sized off-screen NSBitmapImageRep context —
    # NSImage.lockFocus() instead renders at the screen's backing scale
    # factor (e.g. 2x on Retina), silently doubling the pixel dimensions.
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.setCurrentContext_(ctx)
    font = NSFont.systemFontOfSize_(size * 0.78)
    s = NSAttributedString.alloc().initWithString_attributes_(emoji, {"NSFont": font})
    text_size = s.size()
    s.drawAtPoint_(((size - text_size.width) / 2, (size - text_size.height) / 2))
    NSGraphicsContext.setCurrentContext_(None)
    data = rep.representationUsingType_properties_(NSPNGFileType, None)
    data.writeToFile_atomically_(str(out_path), True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size, name in SIZES:
            render_emoji_png(EMOJI, size, iconset / name)
        out = HERE / "icon.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
