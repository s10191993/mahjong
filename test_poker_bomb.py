# -*- coding: utf-8 -*-
"""炸彈彩池與遊戲結算測試（純引擎）。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from poker_game import PokerTable, STREETS


def play_out(t):
    g = 0
    while t.phase in STREETS and g < 200:
        g += 1
        s = t.to_act
        if s is None:
            break
        a = t.legal_actions(s)
        t.act(s, "check" if "check" in a else ("call" if "call" in a else "fold"))
    return t


print("[1] 炸彈彩池：每家 5 大盲底注、跳過翻牌前、直接翻牌")
t = PokerTable(10, 20, 1000, seed=5)
for s in range(4):
    t.seat_player(s, f"P{s}")
before = sum(p.stack for p in t.players.values())
t.start_hand(bomb_pot=True)
ante = 20 * 5
assert t.phase == "flop", t.phase
assert len(t.board) == 3, t.board
assert t.pot == ante * 4, t.pot
assert all(p.invested == ante for p in t.players.values()), \
    {s: p.invested for s, p in t.players.items()}
assert all(p.bet == 0 for p in t.players.values()), "翻牌這輪下注要從 0 開始"
assert t.current_bet == 0, "沒人下注，應可直接過牌"
assert t.is_bomb and t.public_state()["is_bomb"]
assert "check" in t.legal_actions(t.to_act)
print(f"    底注 {ante}／人、底池 {t.pot}、公牌 {len(t.board)} 張、"
      f"階段 {t.phase}、可過牌 ✔")

print("\n[2] 炸彈彩池打完 → 五張公牌、籌碼守恆")
play_out(t)
after = sum(p.stack for p in t.players.values()) + t.pot
assert t.phase == "over" and len(t.board) == 5, (t.phase, t.board)
assert after == before, f"籌碼不守恆 {before} → {after}"
print(f"    結果 {t.result['type']}｜公牌 5 張｜籌碼守恆 {after} ✔")

print("\n[3] 一般手不受影響（仍有盲注與翻牌前）")
t2 = PokerTable(10, 20, 1000, seed=5)
for s in range(4):
    t2.seat_player(s, f"Q{s}")
t2.start_hand()                      # 不帶 bomb_pot
assert t2.phase == "preflop" and t2.board == [], (t2.phase, t2.board)
assert t2.pot == 10 + 20, t2.pot
assert not t2.is_bomb
print(f"    階段 {t2.phase}、底池 {t2.pot}（小盲+大盲）、無公牌 ✔")

print("\n[4] 底注不足者自動全下並產生邊池")
t3 = PokerTable(10, 20, 1000, seed=6)
t3.seat_player(0, "短碼", 60)
t3.seat_player(1, "B", 1000)
t3.seat_player(2, "C", 1000)
b3 = sum(p.stack for p in t3.players.values())
t3.start_hand(bomb_pot=True)
assert t3.players[0].stack == 0 and t3.players[0].all_in
assert t3.players[0].invested == 60, t3.players[0].invested
assert t3.pot == 60 + 100 + 100, t3.pot
play_out(t3)
a3 = sum(p.stack for p in t3.players.values()) + t3.pot
assert a3 == b3, f"籌碼不守恆 {b3} → {a3}"
pots = t3.result.get("pots")
assert pots and len(pots) >= 2, f"應切出主池與邊池，實得 {pots}"
print(f"    短碼投入 60 全下、底池 {60+200}｜邊池 {pots}｜守恆 ✔")

print("\n[5] 遊戲結算：買入／目前／淨輸贏，依淨輸贏排序")
t4 = PokerTable(10, 20, 1000, seed=9)
for s in range(3):
    t4.seat_player(s, f"R{s}")
t4.players[0].stack = 1500
t4.players[1].stack = 800
t4.players[2].stack = 400
t4.players[2].rebuy_total = 500          # 有補碼
rows = t4.settlement(1000)
assert [r["seat"] for r in rows] == [0, 1, 2], rows
assert rows[0]["net"] == 500, rows[0]
assert rows[1]["net"] == -200, rows[1]
assert rows[2]["buyin"] == 1500 and rows[2]["net"] == -1100, rows[2]
print("    " + "｜".join(
    f"{r['name']} 買入{r['buyin']} 目前{r['stack']} 淨{r['net']:+d}" for r in rows) + " ✔")

print("\n[6] 兩人炸彈彩池也正常")
t5 = PokerTable(25, 50, 2000, seed=12)
t5.seat_player(0, "X")
t5.seat_player(1, "Y")
b5 = sum(p.stack for p in t5.players.values())
t5.start_hand(bomb_pot=True)
assert t5.pot == 50 * 5 * 2, t5.pot
assert t5.phase == "flop" and len(t5.board) == 3
play_out(t5)
a5 = sum(p.stack for p in t5.players.values()) + t5.pot
assert a5 == b5, f"籌碼不守恆 {b5} → {a5}"
print(f"    兩人底注 {50*5}／人、底池 {50*5*2}｜守恆 ✔")

print("\n炸彈彩池／遊戲結算測試全部通過 ✔")
