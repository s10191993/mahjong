# -*- coding: utf-8 -*-
"""計分專項測試：用手工牌局驗證各台數。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import mahjong as mj
from game import Game, Meld, score_hand


def mkgame(dealer=1, round_wind="we", streak=0):
    g = Game(dealer=dealer, round_wind=round_wind, dealer_streak=streak)
    g.start()
    return g


def score(hand, melds=None, flowers=None, seat=0, dealer=1, self_draw=True,
          win_tile=None, ctx_extra=None):
    g = mkgame(dealer=dealer)
    p = g.players[seat]
    p.hand = mj.sort_hand(list(hand))
    p.melds = melds or []
    p.flowers = flowers or []
    wt = mj.win_type(p.hand, p.exposed_meld_count)
    ctx = {"win_type": wt or "normal"}
    if ctx_extra:
        ctx.update(ctx_extra)
    res = score_hand(g, seat, win_tile or p.hand[-1], self_draw, ctx)
    names = [n for n, _ in res["detail"]]
    return res["total"], names, res["detail"]


def has(names, *want):
    return all(w in names for w in want)


# 1) 哩咕哩咕（全對）自摸門清
ligu = ["m1","m1","p2","p2","s3","s3","we","we","ws","ws","dz","dz","df","df","db","db","db"]
tot, names, d = score(ligu, self_draw=True)
assert "哩咕哩咕(全對)" in names, names
assert has(names, "自摸","門清","門清自摸"), names
print("1 哩咕哩咕：", tot, d)

# 2) 大不搭（1-4-7 間距全=3）自摸門清
buda = ["m1","m4","m7","p1","p4","p7","s1","s4","s7","we","ws","ww","wn","dz","df","db","db"]
tot, names, d = score(buda, self_draw=True)
assert "大不搭" in names, names
print("2 大不搭：", tot, d)

# 2b) 小不搭（條 1-4-8 有一段間距=4）
buda_s = ["m1","m4","m7","p1","p4","p7","s1","s4","s8","we","ws","ww","wn","dz","df","db","db"]
tot, names, d = score(buda_s, self_draw=True)
assert "小不搭" in names, names
print("2b 小不搭：", tot, d)

# 3) 清一色 + 對對胡 + 五暗刻（自摸）
qing = ["m1","m1","m1","m2","m2","m2","m3","m3","m3","m4","m4","m4","m5","m5","m5","m9","m9"]
tot, names, d = score(qing, self_draw=True)
assert has(names, "清一色","對對胡","五暗刻"), names
print("3 清一色對對五暗刻：", tot, d)

# 4) 大三元（自摸）
big3 = ["dz","dz","dz","df","df","df","db","db","db","m1","m2","m3","m4","m5","m6","p9","p9"]
tot, names, d = score(big3, self_draw=True)
assert "大三元" in names, names
print("4 大三元：", tot, d)

# 5) 全求人：五組全靠別人碰來 + 單釣食胡
melds5 = [Meld("pong", ["m1"]*3, 0), Meld("pong", ["p2"]*3, 2),
          Meld("pong", ["s3"]*3, 3), Meld("pong", ["s6"]*3, 0),
          Meld("pong", ["we"]*3, 2)]
tot, names, d = score(["dz","dz"], melds=melds5, self_draw=False, win_tile="dz")
assert has(names, "全求人","對對胡"), names
print("5 全求人：", tot, d)

# 6) 平胡：全順、將非字、兩面聽、門清食胡
ph = ["m1","m2","m3","m4","m5","m6","p1","p2","p3","s1","s2","s3","s7","s8","p9","p9","s6"]
tot, names, d = score(ph, self_draw=False, win_tile="s6")
assert "平胡" in names, names
assert "獨聽" not in names, names
print("6 平胡：", tot, d)

# 7) 獨聽（單吊將）：食胡，聽一張
dan = ["m1","m2","m3","m4","m5","m6","p1","p2","p3","s1","s2","s3","s7","s8","s9","p5","p5"]
tot, names, d = score(dan, self_draw=False, win_tile="p5")
assert "獨聽" in names, names
print("7 獨聽：", tot, d)

# 8) 槓上開花（自摸情境旗標）
tot, names, d = score(big3, self_draw=True, ctx_extra={"after_kong": True})
assert "槓上開花" in names, names
print("8 槓上開花：", tot, d)

# 9) 搶槓（食胡情境旗標）
tot, names, d = score(big3, self_draw=False, win_tile="p9", ctx_extra={"qianggang": True})
assert "搶槓" in names, names
print("9 搶槓：", tot, d)

# 10) 莊家台：只要莊家有關就算（莊家胡／莊家放槍／別人自摸），閒家放槍給閒家才不算
def dealer_case(winner, discarder, self_draw=False, dealer=0, streak=0):
    g = mkgame(dealer=dealer, streak=streak)
    p = g.players[winner]
    p.melds = [Meld("pong", ["s5"]*3, 1), Meld("chow", ["p7","p8","p9"], 1)]
    p.hand = ["m1","m2","m3","m4","m5","m6","p1","p2","p3","dz"]
    p.flowers = []
    g.any_claim, g.discard_count = True, 8
    if self_draw:
        p.hand.append("dz"); p.hand = mj.sort_hand(p.hand)
        g.turn, g.phase, g.last_draw = winner, "await_discard", "dz"
        g.declare_tsumo(winner)
    else:
        g.turn, g.phase = discarder, "await_discard"
        if "dz" not in g.players[discarder].hand:
            g.players[discarder].hand.append("dz")
        g.discard(discarder, "dz")
        g.claim(winner, "hu")
    names = [n for n, _ in g.result["tai_detail"]]
    return g.result["tai"], names

t, n = dealer_case(winner=0, discarder=2)                 # 莊家胡
assert "莊家" in n, n
t_dealer_deal, n = dealer_case(winner=2, discarder=0)     # 莊家放槍
assert "莊家放槍" in n, n
t_other_deal, n = dealer_case(winner=2, discarder=3)      # 閒家放槍給閒家
assert not any("莊家" in x for x in n), n
assert t_dealer_deal == t_other_deal + 1, (t_dealer_deal, t_other_deal)
t, n = dealer_case(winner=2, discarder=None, self_draw=True)   # 閒家自摸
assert "莊家" in n, n
print(f"10 莊家台：莊家放槍 {t_dealer_deal} 台 > 閒家放槍 {t_other_deal} 台 ✔")

print("\n計分專項測試全部通過 ✔")
