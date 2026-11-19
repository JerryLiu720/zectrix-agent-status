#!/usr/bin/env python3
"""wrap_lines / clean_text 的回归测试（无第三方依赖，直接 python3 运行）。

用法：python3 tests/test_wrap.py
失败时退出码非 0，可直接接进 CI 或 pre-commit。
"""
import importlib.util
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("agent_status", os.path.join(ROOT, "agent_status.py"))
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

W, MAX_W = 400, 400 - 32
d = ImageDraw.Draw(Image.new("1", (W, 300), 1))


def width(s):
    return d.textlength(s, font=mod.font(14))


def check(name, text, max_lines=2):
    lines = mod.wrap_lines(d, text, 14, MAX_W, max_lines)
    assert 1 <= len(lines) <= max_lines, f"{name}: 行数 {len(lines)}"
    for ln in lines:
        assert width(ln) <= MAX_W + 0.01, f"{name}: 行宽 {width(ln):.1f} > {MAX_W} ({ln!r})"
    return lines


def main():
    # 1. 中文长句：按字折行，两行都不越界
    lines = check("中文长句", "这是一个比较长的测试回复，用来复现首行被裁切的问题，包含中英混排与数字 12345。")
    assert lines[0].startswith("这是一个"), lines

    # 2. 英文段落：不得从单词中间断开
    lines = check("英文段落", "I refactored the authentication layer and added retry handling for the token refresh endpoint, then ran the full test suite.")
    for ln in lines[:-1]:
        assert ln.endswith((" ",)) is False and not ln.endswith("-"), ln
    joined = " ".join(lines)
    assert "refactored the authentication" in joined, lines

    # 3. 超长 URL：允许按字符切，但加省略号后仍不越界
    lines = check("超长URL", "See https://example.com/very/long/path/that/keeps/going/and/going/forever/until/it/overflows for details.")
    assert lines[-1].endswith("…"), lines

    # 4. 前缀 + 正文（issue 里的场景）：前缀必须和正文同在第一行
    lines = check("前缀+正文", "3 分钟前 · 这是一个比较长的测试回复，用来复现首行被裁切的问题，包含中文和 English mixed content。")
    assert lines[0].startswith("3 分钟前 · "), lines
    assert len(lines[0]) > len("3 分钟前 · ") + 4, "前缀后没有正文，说明前缀单独占了一行"

    # 5. 空文本不崩
    lines = mod.wrap_lines(d, "", 14, MAX_W, 2)
    assert lines == [""], lines

    # 6. clean_text 截断不切断英文单词
    out = mod.clean_text("Fixed the authentication retry loop in the token refresh endpoint handler", 40)
    assert out.endswith("…"), out
    assert not out[:-1].endswith(" "), out
    last = out[:-1].split(" ")[-1]
    assert last in ("Fixed", "the", "authentication", "retry", "loop", "in", "token", "refresh", "endpoint", "handler"), out

    # 7. clean_text 去掉 emoji / markdown 标记
    out = mod.clean_text("**bold** `code` 👇 text")
    assert "👇" not in out and "*" not in out and "`" not in out, out

    print("all wrap/clean tests passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
