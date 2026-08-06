# -*- coding: utf-8 -*-
"""
德州撲克 —— 純牌型引擎（無網路依賴，可獨立測試）

牌的編碼：兩個字元 = 點數 + 花色
    點數 23456789TJQKA        花色 s(黑桃) h(紅心) d(方塊) c(梅花)
    例："As" 黑桃A、"Td" 方塊10、"2c" 梅花2

強度以可直接比大小的 tuple 表示：(category, tiebreakers...)
category 由大到小：
    8 同花順  7 四條  6 葫蘆  5 同花  4 順子  3 三條  2 兩對  1 一對  0 高牌
"""
from __future__ import annotations
import random
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VAL = {r: i + 2 for i, r in enumerate(RANKS)}      # 2..14（A=14）
SUIT_CN = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

CAT_NAME = {
    8: "同花順", 7: "四條", 6: "葫蘆", 5: "同花",
    4: "順子", 3: "三條", 2: "兩對", 1: "一對", 0: "高牌",
}
STRAIGHT_FLUSH, FOUR, FULL_HOUSE, FLUSH, STRAIGHT, TRIPS, TWO_PAIR, PAIR, HIGH = 8, 7, 6, 5, 4, 3, 2, 1, 0


def make_deck() -> list[str]:
    return [r + s for s in SUITS for r in RANKS]


def rank_of(card: str) -> int:
    return RANK_VAL[card[0]]


def suit_of(card: str) -> str:
    return card[1]


def card_cn(card: str) -> str:
    """給前端／log 用的可讀字串，例如 'A♠'。"""
    return f"{card[0]}{SUIT_CN[card[1]]}"


# ---------------------------------------------------------------------------
# 5 張牌的強度
# ---------------------------------------------------------------------------
def _straight_high(vals: set[int]) -> int | None:
    """給一組不重複點數，回傳最大順子的頂端點數；沒有順子回傳 None。
    A 可當 1（A-2-3-4-5，頂端視為 5）。"""
    v = set(vals)
    if 14 in v:
        v.add(1)                      # 輪子順 A2345
    best = None
    for high in range(14, 4, -1):
        if all((high - i) in v for i in range(5)):
            best = high
            break
    return best


def eval5(cards: list[str]) -> tuple:
    """回傳 5 張牌的強度 tuple，可直接用 > < 比較。"""
    vals = sorted((rank_of(c) for c in cards), reverse=True)
    suits = [suit_of(c) for c in cards]
    is_flush = len(set(suits)) == 1
    sh = _straight_high(set(vals))

    # 依出現次數分組：(次數, 點數) 由大到小
    counts: dict[int, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = [c for _, c in groups]

    if is_flush and sh:
        return (STRAIGHT_FLUSH, sh)
    if shape[0] == 4:
        quad = groups[0][0]
        kicker = max(v for v in vals if v != quad)
        return (FOUR, quad, kicker)
    if shape[0] == 3 and shape[1] >= 2:
        return (FULL_HOUSE, groups[0][0], groups[1][0])
    if is_flush:
        return (FLUSH, *vals)
    if sh:
        return (STRAIGHT, sh)
    if shape[0] == 3:
        kick = sorted((v for v in vals if v != groups[0][0]), reverse=True)
        return (TRIPS, groups[0][0], *kick)
    if shape[0] == 2 and shape[1] == 2:
        hi, lo = sorted((groups[0][0], groups[1][0]), reverse=True)
        kicker = max(v for v in vals if v not in (hi, lo))
        return (TWO_PAIR, hi, lo, kicker)
    if shape[0] == 2:
        kick = sorted((v for v in vals if v != groups[0][0]), reverse=True)
        return (PAIR, groups[0][0], *kick)
    return (HIGH, *vals)


def best_of(cards: list[str]) -> tuple[tuple, list[str]]:
    """從 5~7 張中挑出最強的 5 張。回傳 (強度, 那 5 張)。"""
    if len(cards) < 5:
        raise ValueError("至少要 5 張牌")
    best_score, best_cards = None, None
    for combo in combinations(cards, 5):
        s = eval5(list(combo))
        if best_score is None or s > best_score:
            best_score, best_cards = s, list(combo)
    return best_score, best_cards


def describe(score: tuple) -> str:
    """把強度 tuple 轉成中文說明，例如「葫蘆 K帶3」。"""
    cat = score[0]
    name = CAT_NAME[cat]
    rv = {v: k for k, v in RANK_VAL.items()}

    def r(v):
        return rv.get(v, str(v))

    if cat == STRAIGHT_FLUSH:
        return f"{name} {r(score[1])} 高" if score[1] != 14 else "皇家同花順"
    if cat == FOUR:
        return f"{name} {r(score[1])}"
    if cat == FULL_HOUSE:
        return f"{name} {r(score[1])}帶{r(score[2])}"
    if cat == FLUSH:
        return f"{name} {r(score[1])} 高"
    if cat == STRAIGHT:
        return f"{name} {r(score[1])} 高"
    if cat == TRIPS:
        return f"{name} {r(score[1])}"
    if cat == TWO_PAIR:
        return f"{name} {r(score[1])}與{r(score[2])}"
    if cat == PAIR:
        return f"{name} {r(score[1])}"
    return f"{name} {r(score[1])}"


def compare(a: list[str], b: list[str]) -> int:
    """比較兩手（各 5~7 張）：a 贏回 1、b 贏回 -1、平手回 0。"""
    sa, _ = best_of(a)
    sb, _ = best_of(b)
    return (sa > sb) - (sa < sb)


# ---------------------------------------------------------------------------
# 自我測試
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    d = make_deck()
    assert len(d) == 52 and len(set(d)) == 52, "整副牌應為 52 張不重複"

    # 各牌型辨識
    cases = [
        (["As", "Ks", "Qs", "Js", "Ts"], STRAIGHT_FLUSH, "皇家同花順"),
        (["9h", "8h", "7h", "6h", "5h"], STRAIGHT_FLUSH, None),
        (["7c", "7d", "7h", "7s", "2c"], FOUR, None),
        (["Kc", "Kd", "Kh", "3s", "3c"], FULL_HOUSE, None),
        (["Ac", "Jc", "9c", "6c", "3c"], FLUSH, None),
        (["9c", "8d", "7h", "6s", "5c"], STRAIGHT, None),
        (["5c", "4d", "3h", "2s", "Ac"], STRAIGHT, None),      # 輪子順
        (["Qc", "Qd", "Qh", "8s", "3c"], TRIPS, None),
        (["Jc", "Jd", "4h", "4s", "9c"], TWO_PAIR, None),
        (["Tc", "Td", "8h", "5s", "2c"], PAIR, None),
        (["Ac", "Qd", "9h", "6s", "3c"], HIGH, None),
    ]
    for cards, cat, note in cases:
        s = eval5(cards)
        assert s[0] == cat, f"{cards} 應為 {CAT_NAME[cat]}，實得 {CAT_NAME[s[0]]}"
    # 輪子順的頂端是 5，不是 A
    assert eval5(["5c", "4d", "3h", "2s", "Ac"])[1] == 5, "A2345 頂端應為 5"
    # 同花順 > 四條 > 葫蘆 ...
    order = [eval5(c) for c, _, _ in cases[:1] + cases[2:]]
    for i in range(len(order) - 1):
        assert order[i] > order[i + 1], f"牌型大小順序錯誤於第 {i} 組"

    # 7 張取最佳 5 張
    score, five = best_of(["As", "Ks", "Qs", "Js", "Ts", "2c", "3d"])
    assert score[0] == STRAIGHT_FLUSH and set(five) == {"As", "Ks", "Qs", "Js", "Ts"}
    # 同點數比踢腳
    assert compare(["Ac", "Ad", "Kc", "9d", "5s"], ["Ac", "Ah", "Qc", "9d", "5s"]) == 1
    # 公牌五張同花，兩人都用公牌 → 平手
    board = ["2c", "5c", "9c", "Jc", "Kc"]
    assert compare(board + ["7d", "8h"], board + ["3d", "4h"]) == 0, "都用公牌應平手"
    # 兩對比較：大對優先
    assert compare(["Kc", "Kd", "3h", "3s", "9c"], ["Qc", "Qd", "Jh", "Js", "9c"]) == 1

    # 隨機對局不會爆
    rng = random.Random(0)
    for _ in range(2000):
        deck = make_deck()
        rng.shuffle(deck)
        board = deck[:5]
        a, b = deck[5:7], deck[7:9]
        r = compare(board + a, board + b)
        assert r in (-1, 0, 1)

    print("poker.py 全部自我測試通過 ✔")
    s, five = best_of(["Ah", "Kh", "Qh", "Jh", "9h", "2c", "3d"])
    print("範例：", [card_cn(c) for c in five], "→", describe(s))
