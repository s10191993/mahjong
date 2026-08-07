# -*- coding: utf-8 -*-
"""秀牌與 2-7 獎金測試（純引擎，不需啟動伺服器）。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from poker_game import PokerTable, STREETS


def fold_win_for(seat0_hole, n=4, sb=10, bb=20, bounty=True, seed=3):
    """做出「座位0 收池、其他人全蓋」的局面，回傳 table。"""
    t = PokerTable(sb, bb, 1000, seed=seed, bounty_27=bounty)
    for s in range(n):
        t.seat_player(s, f"P{s}")
    total_before = sum(p.stack for p in t.players.values())
    t.start_hand()
    t.players[0].hole = list(seat0_hole)
    guard = 0
    while t.phase in STREETS and guard < 60:
        guard += 1
        s = t.to_act
        if s is None:
            break
        if s == 0:
            a = t.legal_actions(0)
            t.act(0, "check" if "check" in a else "call")
        else:
            t.act(s, "fold")
    return t, total_before


def total(t):
    return sum(p.stack for p in t.players.values()) + t.pot


print("[1] 收池不秀牌 → 沒有獎金")
t, before = fold_win_for(["2c", "7d"])
assert t.result["type"] == "fold_win" and t.result["winners"] == [0]
assert "bounty27" not in t.result, "沒秀牌不該有獎金"
assert not t.result.get("shown"), "沒秀牌不該亮牌"
print(f"    收池 {t.result['pot']}｜無獎金、無亮牌 ✔")

print("\n[2] 秀牌且是 2·7 → 每家付 2.5 大盲")
assert t.show_cards(0), "應可秀牌"
b = t.result["bounty27"]
assert b["each"] == int(round(20 * 2.5)) == 50, b
assert set(b["paid"].keys()) == {1, 2, 3}, b
assert b["total"] == 150, b
assert t.result["shown"][0]["hole"] == ["2c", "7d"]
assert total(t) == before, f"籌碼不守恆 {before} → {total(t)}"
print(f"    每家付 {b['each']}、共收 {b['total']}｜籌碼守恆 {total(t)} ✔")
assert not t.show_cards(0), "不可重複秀牌"
print("    重複秀牌被擋 ✔")

print("\n[3] 秀牌但不是 2·7 → 只亮牌、沒獎金")
t2, before2 = fold_win_for(["As", "Kd"], seed=4)
assert t2.show_cards(0)
assert "bounty27" not in t2.result, "非 2·7 不該有獎金"
assert t2.result["shown"][0]["hole"] == ["As", "Kd"]
assert total(t2) == before2
print("    亮牌但無獎金、籌碼守恆 ✔")

print("\n[4] 規則關閉 → 即使 2·7 也沒獎金")
t3, before3 = fold_win_for(["2c", "7d"], bounty=False)
assert t3.show_cards(0)
assert "bounty27" not in t3.result
assert total(t3) == before3
print("    關閉時無獎金 ✔")

print("\n[5] 攤牌贏且是 2·7 → 自動給獎金（不用按秀牌）")
t4 = PokerTable(10, 20, 1000, seed=11)
for s in range(3):
    t4.seat_player(s, f"S{s}")
before4 = sum(p.stack for p in t4.players.values())
t4.start_hand()
# 直接布置到河牌後的局面，只攤牌一次（跑下注迴圈會自動攤牌，再手動叫一次會重複派彩）
for s in range(3):
    p = t4.players[s]
    need = 100 - p.invested          # 每人統一投入 100
    p.stack -= need
    p.invested += need
    p.bet = 0
    t4.pot += need
t4.players[0].hole = ["2c", "7d"]     # 2-7 中葫蘆，一定贏
t4.players[1].hole = ["3h", "4s"]
t4.players[2].hole = ["5h", "6s"]
t4.board = ["2h", "2s", "7h", "7s", "Kd"]
t4.phase = "river"
t4._showdown()
assert t4.result["type"] == "showdown"
assert 0 in t4.result["winners"], t4.result["winners"]
assert "bounty27" in t4.result, "攤牌拿 2-7 贏應自動有獎金"
print(f"    攤牌贏家 {t4.result['winners']}｜獎金 每家 "
      f"{t4.result['bounty27']['each']}、共 {t4.result['bounty27']['total']} ✔")
assert total(t4) == before4, f"籌碼不守恆 {before4} → {total(t4)}"
print(f"    籌碼守恆 {total(t4)} ✔")

print("\n[6] 籌碼不夠的人只付到底，不會變負數")
t5, before5 = fold_win_for(["2c", "7d"], seed=7)
t5.players[2].stack = 20          # 只剩 20，付不出 50
assert t5.show_cards(0)
assert t5.players[2].stack == 0, t5.players[2].stack
assert t5.result["bounty27"]["paid"][2] == 20
print(f"    短碼者只付 20（不足 50）、籌碼歸零不為負 ✔")

print("\n[7] has_27 判定")
cases = [(["2c", "7d"], True), (["7s", "2h"], True), (["2c", "2d"], False),
         (["7c", "8d"], False), (["2c", "Td"], False)]
for hole, want in cases:
    got = PokerTable.has_27(hole)
    assert got == want, f"{hole} 應為 {want}"
print(f"    {len(cases)} 組判定全部正確 ✔")

print("\n秀牌／2-7 獎金測試全部通過 ✔")
