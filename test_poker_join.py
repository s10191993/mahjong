# -*- coding: utf-8 -*-
"""德州：中途加入／中途離開（純引擎，不需啟動伺服器）。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from poker_game import PokerTable, STREETS


def play_out(t, limit=200):
    g = 0
    while t.phase in STREETS and g < limit:
        g += 1
        s = t.to_act
        if s is None:
            break
        a = t.legal_actions(s)
        t.act(s, "check" if "check" in a else ("call" if "call" in a else "fold"))
    return t


def chips(t):
    return sum(p.stack for p in t.players.values()) + t.pot


print("[1] 牌局進行中入座：這手旁觀，下一手才發牌")
t = PokerTable(10, 20, 1000, seed=21)
for s in range(3):
    t.seat_player(s, f"P{s}")
t.start_hand()
assert t.phase in STREETS
before_join = chips(t)
t.join_mid_game(3, "新來的", 1000)
p = t.players[3]
assert p.sitting_out and p.hole == [] and p.invested == 0, "本手不該參與"
assert chips(t) == before_join + 1000, "新玩家帶進 1000 籌碼"
print(f"    入座後：sitting_out={p.sitting_out}、無底牌、無投入 ✔")

play_out(t)
assert t.phase == "over"
t.start_hand()
assert not t.players[3].sitting_out, "下一手應該參與"
assert len(t.players[3].hole) == 2, "下一手應該有底牌"
print(f"    下一手：發到 {t.players[3].hole}、正式參戰 ✔")

print("\n[2] 輪到誰時離開 → 自動蓋牌，牌局不卡住")
t2 = PokerTable(10, 20, 1000, seed=22)
for s in range(4):
    t2.seat_player(s, f"Q{s}")
b2 = chips(t2)
t2.start_hand()
victim = t2.to_act
t2.mark_left(victim)
assert t2.players[victim].folded and t2.players[victim].left
assert t2.to_act != victim or t2.phase == "over", "行動權應已交出"
play_out(t2)
assert t2.phase == "over", f"牌局卡在 {t2.phase}"
assert chips(t2) == b2, f"籌碼不守恆 {b2} → {chips(t2)}"
print(f"    離開者自動蓋牌、牌局打完（{t2.result['type']}）、籌碼守恆 ✔")

print("\n[3] 非當前行動者離開 → 不影響其他人行動順序")
t3 = PokerTable(10, 20, 1000, seed=23)
for s in range(4):
    t3.seat_player(s, f"R{s}")
b3 = chips(t3)
t3.start_hand()
cur = t3.to_act
other = next(s for s in t3.players if s != cur and t3.players[s].can_act())
t3.mark_left(other)
assert t3.to_act == cur, f"行動權不該被改動（原 {cur}，現 {t3.to_act}）"
assert t3.players[other].folded
play_out(t3)
assert t3.phase == "over"
assert chips(t3) == b3, f"籌碼不守恆 {b3} → {chips(t3)}"
print(f"    行動權維持在座位 {cur}、牌局正常打完、籌碼守恆 ✔")

print("\n[4] 離開者的投入留在彩池，下一手才移除")
t4 = PokerTable(10, 20, 1000, seed=24)
for s in range(3):
    t4.seat_player(s, f"S{s}")
b4 = chips(t4)
t4.start_hand()
# 讓某人先投入再離開
leaver = t4.to_act
t4.act(leaver, "call")
invested = t4.players[leaver].invested
assert invested > 0
t4.mark_left(leaver)
assert leaver in t4.players, "這手還沒結束，不該立刻移除"
assert t4.players[leaver].invested == invested, "投入金額要保留給彩池計算"
play_out(t4)
assert chips(t4) == b4, f"籌碼不守恆 {b4} → {chips(t4)}"
print(f"    投入 {invested} 留在彩池、籌碼守恆 ✔")
t4.start_hand()
assert leaver not in t4.players, "下一手應已移除"
print("    下一手已移除該座位 ✔")

print("\n[5] 座位佔用判斷：這手用到的座位不能被新人坐")
t5 = PokerTable(10, 20, 1000, seed=25)
for s in range(3):
    t5.seat_player(s, f"T{s}")
t5.start_hand()
busy = [s for s in range(3) if t5.seat_busy(s)]
assert busy == [0, 1, 2] or len(busy) >= 2, f"下過盲注/投入的座位應算佔用，實得 {busy}"
t5.mark_left(0)
assert t5.seat_busy(0), "離開但尚未清掉的座位仍算佔用"
play_out(t5)
assert not t5.seat_busy(1), "牌局結束後座位不再算佔用"
print(f"    牌局中佔用 {busy}、離開者仍佔用、結束後釋放 ✔")

print("\n[6] 人來人往後籌碼仍守恆（連跑 8 手）")
t6 = PokerTable(10, 20, 1000, seed=26)
for s in range(4):
    t6.seat_player(s, f"U{s}")
expected = 4000
for hand in range(8):
    if len(t6.active_seats()) < 2:
        break
    # 上一手離開的人會在 start_hand 被移除，帶走自己剩下的籌碼
    expected -= sum(p.stack for p in t6.players.values() if p.left)
    t6.start_hand()
    if hand % 3 == 1:                      # 中途有人離開
        v = t6.to_act
        if v is not None:
            t6.mark_left(v)
    play_out(t6)
    if hand % 3 == 2:                      # 中途有人加入
        free = next((s for s in range(8) if s not in t6.players), None)
        if free is not None:
            t6.join_mid_game(free, f"新{free}", 1000)
            expected += 1000
    assert chips(t6) == expected, f"第{hand+1}手籌碼不守恆 {expected} → {chips(t6)}"
print(f"    8 手人來人往，籌碼始終守恆（最終 {chips(t6)}）✔")

print("\n中途加入／離開測試全部通過 ✔")
