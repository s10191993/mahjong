# -*- coding: utf-8 -*-
"""
台灣麻將 16 張 —— 純規則引擎（無網路依賴，可獨立測試）

牌的編碼採用短字串 code：
    萬  m1..m9     筒  p1..p9     條  s1..s9
    風  we(東) ws(南) ww(西) wn(北)
    箭  dz(中) df(發) db(白)
    花  f1..f8   (f1春 f2夏 f3秋 f4冬 f5梅 f6蘭 f7菊 f8竹)

胡牌判斷以 34 種序數/字牌的 count 陣列進行遞迴拆解，
花牌不進手牌（補花後移到花區）。
"""
from __future__ import annotations
import random
from typing import Optional

# ---------------------------------------------------------------------------
# 牌的定義
# ---------------------------------------------------------------------------
SUITS = ("m", "p", "s")                     # 萬 筒 條
HONORS = ("we", "ws", "ww", "wn", "dz", "df", "db")
WINDS = ("we", "ws", "ww", "wn")
DRAGONS = ("dz", "df", "db")
FLOWERS = tuple(f"f{i}" for i in range(1, 9))

# 34 種可入手的牌（不含花），固定順序 → 給 count 陣列用
KINDS: list[str] = (
    [f"m{i}" for i in range(1, 10)]
    + [f"p{i}" for i in range(1, 10)]
    + [f"s{i}" for i in range(1, 10)]
    + list(HONORS)
)
KIND_INDEX = {k: i for i, k in enumerate(KINDS)}

# 牌面顯示（Unicode 麻將牌）
_UNI = {
    "m1": "🀇", "m2": "🀈", "m3": "🀉", "m4": "🀊", "m5": "🀋",
    "m6": "🀌", "m7": "🀍", "m8": "🀎", "m9": "🀏",
    "p1": "🀙", "p2": "🀚", "p3": "🀛", "p4": "🀜", "p5": "🀝",
    "p6": "🀞", "p7": "🀟", "p8": "🀠", "p9": "🀡",
    "s1": "🀐", "s2": "🀑", "s3": "🀒", "s4": "🀓", "s5": "🀔",
    "s6": "🀕", "s7": "🀖", "s8": "🀗", "s9": "🀘",
    "we": "🀀", "ws": "🀁", "ww": "🀂", "wn": "🀃",
    "dz": "🀄", "df": "🀅", "db": "🀆",
    "f1": "🀦", "f2": "🀧", "f3": "🀨", "f4": "🀩",   # 春夏秋冬
    "f5": "🀢", "f6": "🀣", "f7": "🀤", "f8": "🀥",   # 梅蘭菊竹
}
_NAME = {
    "we": "東", "ws": "南", "ww": "西", "wn": "北",
    "dz": "中", "df": "發", "db": "白",
    "f1": "春", "f2": "夏", "f3": "秋", "f4": "冬",
    "f5": "梅", "f6": "蘭", "f7": "菊", "f8": "竹",
}


def unicode_of(code: str) -> str:
    return _UNI.get(code, code)


def name_of(code: str) -> str:
    if code in _NAME:
        return _NAME[code]
    suit = {"m": "萬", "p": "筒", "s": "條"}.get(code[0], "")
    return f"{code[1]}{suit}" if suit else code


def is_flower(code: str) -> bool:
    return code.startswith("f")


def is_honor(code: str) -> bool:
    return code in HONORS


def is_suited(code: str) -> bool:
    return code[0] in SUITS


def build_wall() -> list[str]:
    """整副台灣麻將 144 張：34 種各 4 張 + 8 花。"""
    wall: list[str] = []
    for k in KINDS:
        wall.extend([k] * 4)
    wall.extend(FLOWERS)
    return wall


# ---------------------------------------------------------------------------
# 胡牌判斷
# ---------------------------------------------------------------------------
def _counts(tiles: list[str]) -> list[int]:
    c = [0] * 34
    for t in tiles:
        c[KIND_INDEX[t]] += 1
    return c


def _can_form_melds(c: list[int], need: int) -> bool:
    """counts c 能否剛好拆成 need 組面子（順子或刻子），無剩牌。"""
    if need == 0:
        return all(v == 0 for v in c)
    # 找第一張非零牌
    i = next((idx for idx, v in enumerate(c) if v > 0), None)
    if i is None:
        return False
    # 刻子
    if c[i] >= 3:
        c[i] -= 3
        if _can_form_melds(c, need - 1):
            c[i] += 3
            return True
        c[i] += 3
    # 順子（只有序數牌可以，且不能跨花色）
    if i < 27:                       # 序數牌
        rank = i % 9                 # 0..8
        if rank <= 6 and c[i + 1] > 0 and c[i + 2] > 0:
            c[i] -= 1
            c[i + 1] -= 1
            c[i + 2] -= 1
            if _can_form_melds(c, need - 1):
                c[i] += 1
                c[i + 1] += 1
                c[i + 2] += 1
                return True
            c[i] += 1
            c[i + 1] += 1
            c[i + 2] += 1
    return False


def is_winning_hand(concealed: list[str], exposed_melds: int) -> bool:
    """
    concealed：暗手牌（含剛摸/剛胡的那張）
    exposed_melds：已亮出的面子數（碰、槓、吃各算 1 組）
    16 張規則：總共需 5 組面子 + 1 對將。
    暗手需組成 (5 - exposed_melds) 組面子 + 1 對將。
    """
    need = 5 - exposed_melds
    if need < 0:
        return False
    c = _counts(concealed)
    if sum(c) != need * 3 + 2:
        return False
    # 嘗試每一種當「將」（對子）
    for i in range(34):
        if c[i] >= 2:
            c[i] -= 2
            if _can_form_melds(c, need):
                c[i] += 2
                return True
            c[i] += 2
    return False


def winning_tiles(concealed: list[str], exposed_melds: int) -> list[str]:
    """聽哪些牌：把每一種可入手牌試著加入，看是否成胡。回傳可胡的牌 code 清單。"""
    result = []
    for k in KINDS:
        if is_winning_hand(concealed + [k], exposed_melds):
            result.append(k)
    return result


def is_tenpai(concealed: list[str], exposed_melds: int) -> bool:
    """是否聽牌（差一張胡）。"""
    return len(winning_tiles(concealed, exposed_melds)) > 0


# ---------------------------------------------------------------------------
# 面子（吃碰槓）判斷
# ---------------------------------------------------------------------------
def can_pong(hand: list[str], tile: str) -> bool:
    return hand.count(tile) >= 2


def can_kong_from_discard(hand: list[str], tile: str) -> bool:
    """明槓：手上有 3 張與被打出的牌相同。"""
    return hand.count(tile) >= 3


def concealed_kong_options(hand: list[str]) -> list[str]:
    """暗槓：手上任一種有 4 張。"""
    return sorted({t for t in hand if hand.count(t) == 4})


def chow_options(hand: list[str], tile: str) -> list[tuple[str, str]]:
    """
    吃（僅序數牌）：回傳可用來與 tile 組順子的另兩張組合。
    例如 tile=m3，手上有 m1 m2 → 回傳 (m1,m2)。
    """
    if not is_suited(tile):
        return []
    suit = tile[0]
    n = int(tile[1])
    opts: list[tuple[str, str]] = []

    def has(x):
        return f"{suit}{x}" in hand

    # tile 在順子的位置：右端 / 中間 / 左端
    if 3 <= n and has(n - 2) and has(n - 1):
        opts.append((f"{suit}{n-2}", f"{suit}{n-1}"))
    if 2 <= n <= 8 and has(n - 1) and has(n + 1):
        opts.append((f"{suit}{n-1}", f"{suit}{n+1}"))
    if n <= 7 and has(n + 1) and has(n + 2):
        opts.append((f"{suit}{n+1}", f"{suit}{n+2}"))
    return opts


# ---------------------------------------------------------------------------
# 索引小工具（給計分用）
# ---------------------------------------------------------------------------
def counts(tiles: list[str]) -> list[int]:
    return _counts(tiles)


def idx_is_honor(i: int) -> bool:
    return i >= 27


def idx_suit(i: int) -> int:
    """0=萬 1=筒 2=條；字牌回傳 -1。"""
    return i // 9 if i < 27 else -1


def idx_rank(i: int) -> int:
    """序數牌回傳 1..9；字牌回傳 0。"""
    return i % 9 + 1 if i < 27 else 0


def kind_of(i: int) -> str:
    return KINDS[i]


# ---------------------------------------------------------------------------
# 特殊牌型：哩咕哩咕（全對）、十六不搭
# ---------------------------------------------------------------------------
def is_liguligu(tiles: list[str]) -> bool:
    """
    哩咕哩咕（全對子）：17 張全部湊對，因奇數補一組刻子 →「7 對 + 1 刻」。
    （4 張同種視為 2 對，也允許。）條件：無單張、恰有一種是 3 張、其餘皆偶數。
    """
    if len(tiles) != 17:
        return False
    c = _counts(tiles)
    if any(v == 1 for v in c):
        return False
    if sum(1 for v in c if v == 3) != 1:
        return False
    return True


def is_shiliubuda(tiles: list[str]) -> bool:
    """
    十六不搭（大小不搭）：17 張中恰有一組對子當將，其餘全部落單且彼此不搭
    —— 同一花色任兩張間距 ≥3（無法湊順），無任何刻子/多餘對子。
    """
    if len(tiles) != 17:
        return False
    c = _counts(tiles)
    present = [i for i, v in enumerate(c) if v > 0]
    if any(c[i] >= 3 for i in present):
        return False
    if sum(1 for i in present if c[i] == 2) != 1:   # 恰好一對
        return False
    for suit in range(3):
        ranks = sorted(idx_rank(i) for i in present if idx_suit(i) == suit)
        for a in range(len(ranks)):
            for b in range(a + 1, len(ranks)):
                if ranks[b] - ranks[a] <= 2:          # 太近 → 可能搭順
                    return False
    return True


def shiliubuda_tier(tiles: list[str]) -> str | None:
    """
    十六不搭分級：
      'big'   大不搭 —— 每個花色的相鄰牌間距「剛好都是 3」（如 1-4-7）
      'small' 小不搭 —— 是合法不搭（間距 ≥3）但不是全部剛好 3（如 1-4-8）
      None    不是十六不搭
    """
    if not is_shiliubuda(tiles):
        return None
    c = _counts(tiles)
    present = [i for i, v in enumerate(c) if v > 0]
    all_exactly_3 = True
    saw_gap = False
    for suit in range(3):
        ranks = sorted(idx_rank(i) for i in present if idx_suit(i) == suit)
        for a in range(len(ranks) - 1):
            saw_gap = True
            if ranks[a + 1] - ranks[a] != 3:
                all_exactly_3 = False
    if not saw_gap:
        return "small"
    return "big" if all_exactly_3 else "small"


def win_type(concealed: list[str], exposed_melds: int) -> str | None:
    """回傳胡牌型：'normal' | 'liguligu' | 'shiliubuda'，不胡回傳 None。
    特殊牌型必須門清無亮牌（exposed_melds==0）。"""
    if is_winning_hand(concealed, exposed_melds):
        return "normal"
    if exposed_melds == 0:
        if is_liguligu(concealed):
            return "liguligu"
        if is_shiliubuda(concealed):
            return "shiliubuda"
    return None


def can_win(concealed: list[str], exposed_melds: int) -> bool:
    return win_type(concealed, exposed_melds) is not None


# ---------------------------------------------------------------------------
# 拆牌枚舉（給計分判斷 對對胡/平胡/暗刻/一色 等）
# 回傳 (pair_index, melds)，melds = [('pung', i) | ('chow', i)]（i 為牌索引，chow 取最小張）
# ---------------------------------------------------------------------------
def iter_decompositions(concealed: list[str], need: int):
    c = _counts(concealed)
    if sum(c) != need * 3 + 2:
        return
    for pair in range(34):
        if c[pair] >= 2:
            c[pair] -= 2
            yield from _decomp(c, need, [], pair)
            c[pair] += 2


def _decomp(c, need, acc, pair):
    if need == 0:
        if all(v == 0 for v in c):
            yield (pair, list(acc))
        return
    i = next((idx for idx, v in enumerate(c) if v > 0), None)
    if i is None:
        return
    if c[i] >= 3:
        c[i] -= 3
        acc.append(("pung", i))
        yield from _decomp(c, need - 1, acc, pair)
        acc.pop()
        c[i] += 3
    if i < 27 and (i % 9) <= 6 and c[i + 1] > 0 and c[i + 2] > 0:
        c[i] -= 1
        c[i + 1] -= 1
        c[i + 2] -= 1
        acc.append(("chow", i))
        yield from _decomp(c, need - 1, acc, pair)
        acc.pop()
        c[i] += 1
        c[i + 1] += 1
        c[i + 2] += 1


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def sort_hand(hand: list[str]) -> list[str]:
    """依 KINDS 順序排序手牌，方便顯示。"""
    return sorted(hand, key=lambda t: KIND_INDEX.get(t, 999))


# ---------------------------------------------------------------------------
# 自我測試
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp950 主控台相容
    except Exception:
        pass
    assert len(build_wall()) == 144, "整副牌應為 144 張"
    # 一個標準胡牌：m1m2m3 m4m5m6 m7m8m9 p1p2p3 s1s2s3 + 將 dz dz  (5 順 + 1 將 = 17 張)
    win = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9",
           "p1", "p2", "p3", "s1", "s2", "s3", "dz", "dz"]
    assert is_winning_hand(win, 0), "應判為胡"
    # 有 2 組亮牌時，暗手只需 3 組 + 將 = 11 張
    win2 = ["m1", "m2", "m3", "m4", "m5", "m6", "p1", "p2", "p3", "dz", "dz"]
    assert is_winning_hand(win2, 2), "含亮牌應判為胡"
    # 非胡
    nohu = ["m1", "m2", "m4", "m4", "m5", "m6", "m7", "m8", "m9",
            "p1", "p2", "p3", "s1", "s2", "s3", "dz", "dz"]
    assert not is_winning_hand(nohu, 0), "不應判為胡"
    # 聽牌測試：缺 m3 或 m6
    tenpai = ["m1", "m2", "m4", "m5", "m6", "m7", "m8", "m9",
              "p1", "p2", "p3", "s1", "s2", "s3", "dz", "dz"]
    wt = winning_tiles(tenpai, 0)
    assert wt == ["m3"], f"此手應只聽 m3，實得 {wt}"
    # 吃
    assert ("m1", "m2") in chow_options(["m1", "m2", "p5"], "m3")
    # 碰
    assert can_pong(["dz", "dz", "m1"], "dz")
    # 哩咕哩咕：7 對 + 1 刻（m1m1 p2p2 s3s3 we we ws ws dz dz db db db）
    ligu = ["m1", "m1", "p2", "p2", "s3", "s3", "we", "we",
            "ws", "ws", "dz", "dz", "df", "df", "db", "db", "db"]
    assert is_liguligu(ligu), "應為哩咕哩咕"
    assert win_type(ligu, 0) == "liguligu"
    assert not is_winning_hand(ligu, 0), "全對子不是標準胡"
    # 十六不搭：各花色 1/4/7 + 全字牌，其中一種成對
    buda = ["m1", "m4", "m7", "p1", "p4", "p7", "s1", "s4", "s7",
            "we", "ws", "ww", "wn", "dz", "df", "db", "db"]
    assert is_shiliubuda(buda), "應為十六不搭"
    assert win_type(buda, 0) == "shiliubuda"
    # 1-4-7 各花色間距全為 3 → 大不搭
    assert shiliubuda_tier(buda) == "big", "1-4-7 應為大不搭"
    # 把條的 7 換成 8（1-4-8，間距 3,4）→ 小不搭
    buda_small = ["m1", "m4", "m7", "p1", "p4", "p7", "s1", "s4", "s8",
                  "we", "ws", "ww", "wn", "dz", "df", "db", "db"]
    assert shiliubuda_tier(buda_small) == "small", "1-4-8 應為小不搭"
    # 拆牌枚舉：五順一將至少一種拆法
    decs = list(iter_decompositions(win, 5))
    assert decs, "應能拆出標準胡的組合"
    print("mahjong.py 全部自我測試通過 ✔")
    print("聽牌可胡：", [name_of(t) for t in wt])
