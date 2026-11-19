#!/usr/bin/env python3
"""重新生成 README 截图（示例数据，不含真实余额）。

用法：python3 scripts/make_screenshots.py
产出：screenshots/page0-3.png、preview.png（2×2）、demo.gif（每帧 1.8s）
"""
import os
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "screenshots")
W, H, GAP = 400, 300, 12


def render(page):
    out = os.path.join(SHOTS, f"page{page}.png")
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "agent_status.py"),
         "--demo", "--page", str(page), "--out", out],
        cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
    )
    return Image.open(out).convert("L")


def main():
    os.makedirs(SHOTS, exist_ok=True)
    pages = [render(i) for i in range(4)]

    preview = Image.new("L", (W * 2 + GAP, H * 2 + GAP), 255)
    for i, im in enumerate(pages):
        preview.paste(im, ((i % 2) * (W + GAP), (i // 2) * (H + GAP)))
    preview.save(os.path.join(SHOTS, "preview.png"))

    pages[0].save(
        os.path.join(SHOTS, "demo.gif"),
        save_all=True, append_images=pages[1:], duration=1800, loop=0,
    )
    print(f"已生成 {len(pages)} 页 + preview.png + demo.gif")


if __name__ == "__main__":
    main()
