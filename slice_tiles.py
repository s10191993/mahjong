# -*- coding: utf-8 -*-
"""
把整副麻將大圖切成一顆一顆的牌面圖，輸出到 static/tiles/。

用法：
    python slice_tiles.py "大圖路徑.png"

作法：自動偵測亮（牌）/ 暗（縫隙）來找格線，不寫死座標。
版面假設：9 欄 × 5 列
    第1列 筒 p1..p9
    第2列 條 s1..s9
    第3列 萬 m1..m9
    第4列 東南西北中發白（後 2 格空白，略過）
    第5列 花 f1..f8（最後 1 格空白，略過）
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "static", "tiles")

# 每一列（由上到下）對應的牌代碼；None＝該格空白不輸出
LAYOUT = [
    ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9"],
    ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"],
    ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"],
    ["we", "ws", "ww", "wn", "dz", "df", "db", None, None],
    ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", None],
]
N_COLS, N_ROWS = 9, 5


def runs_of_true(mask, min_len):
    """回傳 mask 中連續 True 的區段 [(start, end_exclusive), ...]。"""
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(mask) - start >= min_len:
        runs.append((start, len(mask)))
    return runs


def merge_to_count(runs, want, total_len):
    """把偵測到的區段合併/篩選成剛好 want 段（取最寬的幾段並依位置排序）。"""
    if len(runs) <= want:
        return runs
    runs = sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:want]
    return sorted(runs)


def detect_bands(gray, axis, want, bright_thresh=140, ratio=0.55):
    """
    沿著 axis 投影，找出「多數像素偏亮」的帶狀區域＝牌所在的行/列。
    axis=0 → 找欄（沿垂直方向統計）；axis=1 → 找列。
    """
    bright = gray > bright_thresh
    frac = bright.mean(axis=0 if axis == 0 else 1)
    mask = frac > ratio
    est = len(frac) / (want * 1.6)
    runs = runs_of_true(mask, max(5, int(est)))
    return merge_to_count(runs, want, len(frac))


def main():
    if len(sys.argv) < 2:
        print("用法: python slice_tiles.py <大圖路徑>")
        sys.exit(1)
    src = sys.argv[1]
    img = Image.open(src).convert("RGB")
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    print(f"來源圖: {img.width} x {img.height}")

    # 用「非黑邊框」找出牌區範圍，再等距切格（此類整齊排列的牌組圖最穩）
    content = gray > 60                      # 黑色外框以外都算內容（含粉紅空白牌）
    col_has = content.mean(axis=0) > 0.5
    row_has = content.mean(axis=1) > 0.5
    xs = np.where(col_has)[0]
    ys = np.where(row_has)[0]
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    y0, y1 = int(ys[0]), int(ys[-1]) + 1
    cw, ch = (x1 - x0) / N_COLS, (y1 - y0) / N_ROWS
    cols = [(round(x0 + i * cw), round(x0 + (i + 1) * cw)) for i in range(N_COLS)]
    rows = [(round(y0 + j * ch), round(y0 + (j + 1) * ch)) for j in range(N_ROWS)]
    print(f"牌區: x {x0}..{x1}, y {y0}..{y1}　欄寬 {cw:.1f} 列高 {ch:.1f}")

    os.makedirs(OUT_DIR, exist_ok=True)
    pad = 4   # 內縮，避免帶到旁邊的牌或黑邊
    made, tiles = 0, []
    for r, (ry0, ry1) in enumerate(rows):
        for c, (cx0, cx1) in enumerate(cols):
            code = LAYOUT[r][c]
            if not code:
                continue
            box = (cx0 + pad, ry0 + pad, cx1 - pad, ry1 - pad)
            tile = img.crop(box)
            tile.save(os.path.join(OUT_DIR, f"{code}.png"))
            tiles.append((code, tile))
            made += 1
    print(f"完成：輸出 {made} 張到 {OUT_DIR}")

    # 產生一張對照表（contact sheet）方便一眼檢查切得對不對
    tw, th = tiles[0][1].size
    per_row = 9
    rows_n = (len(tiles) + per_row - 1) // per_row
    sheet = Image.new("RGB", (per_row * tw, rows_n * th), "black")
    for i, (code, t) in enumerate(tiles):
        sheet.paste(t, ((i % per_row) * tw, (i // per_row) * th))
    sheet_path = os.path.join(HERE, "slice_check.png")
    sheet.save(sheet_path)
    print(f"對照表: {sheet_path}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
