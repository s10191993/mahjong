# -*- coding: utf-8 -*-
"""測試：骰子決定莊家、圈數推進、整場結束（不需啟動伺服器）。"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import server


class FakeSeat:
    def __init__(self, name):
        self.name = name
        self.score = 0
        self.connected = True
        self.ws = None
        self.token = ""


def mkroom(target=1, seed=42, host=0):
    r = server.Room("T")
    r.seats = [FakeSeat(n) for n in "ABCD"]
    r.base, r.tai_value, r.rounds_target = 100, 20, target
    r.rng.seed(seed)
    r.roll_for_dealer(from_seat=host)
    return r


def win_by(room, seat):
    """讓指定座位自摸胡牌並結算。"""
    room.start_new_hand()
    g = room.game
    p = g.players[seat]
    p.hand = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9",
              "p1", "p2", "p3", "s1", "s2", "s3", "dz", "dz"]
    p.melds, p.flowers = [], []
    g.turn, g.phase, g.last_draw = seat, "await_discard", "s3"
    g.any_claim, g.discard_count = True, 8
    g.declare_tsumo(seat)
    room.settle()
    return g.result


def draw_hand(room):
    """製造一次流局。"""
    room.start_new_hand()
    g = room.game
    g.wall = []
    g._draw_game()
    room.settle()
    return g.result


# 1) 骰子決定莊家：合法範圍、可重現
print("[1] 擲骰決定莊家")
seen = set()
for s in range(30):
    r = mkroom(seed=s)
    d = r.start_dice
    assert len(d["values"]) == 3 and all(1 <= v <= 6 for v in d["values"])
    assert d["total"] == sum(d["values"])
    assert 0 <= d["dealer"] <= 3
    assert d["dealer"] == (0 + d["total"] - 1) % 4, "莊家應由點數從起算位數過去"
    assert r.dealer == d["dealer"] and r.start_dealer == d["dealer"]
    seen.add(d["dealer"])
print(f"    30 次擲骰，莊家落點涵蓋 {sorted(seen)} ✔")

# 起算位置不同 → 莊家跟著位移
r0 = mkroom(seed=7, host=0)
r2 = mkroom(seed=7, host=2)
assert r2.start_dice["dealer"] == (r0.start_dice["dealer"] + 2) % 4
print(f"    從房主位置起算正確（host0→{r0.dealer}, host2→{r2.dealer}）✔")

# 2) 1 圈 = 每家做莊一次
print("\n[2] 1 圈")
r = mkroom(1, seed=42)
start = r.dealer
hands = 0
while not r.finished and hands < 20:
    hands += 1
    win_by(r, (r.dealer + 1) % 4)      # 下家胡 → 換莊
assert r.finished and hands == 4, f"1 圈應 4 局，實得 {hands}"
assert r.dealer == start, "一圈後莊家應轉回起莊"
print(f"    起莊={start}，{hands} 局後結束、莊轉回起莊 ✔")

# 3) 1 將 = 4 圈
print("\n[3] 1 將（4 圈）")
r = mkroom(4, seed=42)
hands = 0
while not r.finished and hands < 40:
    hands += 1
    win_by(r, (r.dealer + 1) % 4)
assert r.finished and hands == 16, f"1 將應 16 局，實得 {hands}"
assert r.round_index == 4
print(f"    {hands} 局後結束，round_index={r.round_index} ✔")

# 4) 連莊 / 流局 都不推進圈數
print("\n[4] 連莊與流局不推進圈數")
r = mkroom(1, seed=42)
d0 = r.dealer
for _ in range(3):
    win_by(r, r.dealer)                 # 莊家自摸 → 連莊
assert r.dealer == d0 and r.round_index == 0 and not r.finished
assert r.dealer_streak == 3
print(f"    連莊 3 次：莊仍為 {d0}、圈數 0、streak={r.dealer_streak} ✔")
for _ in range(2):
    draw_hand(r)                        # 流局 → 連莊
assert r.dealer == d0 and r.round_index == 0
print(f"    流局 2 次：莊仍為 {d0}、圈數 0、streak={r.dealer_streak} ✔")

# 5) 圈風隨圈數推進
print("\n[5] 圈風推進")
r = mkroom(4, seed=42)
winds = []
while not r.finished:
    winds.append(r.progress()["round_wind"])
    win_by(r, (r.dealer + 1) % 4)
seq = [w for i, w in enumerate(winds) if i == 0 or w != winds[i - 1]]
assert seq == ["we", "ws", "ww", "wn"], f"圈風應為東南西北，實得 {seq}"
print(f"    圈風序列 {seq} ✔")

# 6) 結束後有最終排名
print("\n[6] 最終排名")
r = mkroom(1, seed=42)
while not r.finished:
    res = win_by(r, (r.dealer + 1) % 4)
assert "standings" in res, "結束該局應附最終排名"
st = res["standings"]
assert len(st) == 4 and st == sorted(st, key=lambda x: -x["score"])
print(f"    排名（依分數遞減）：{[(x['name'], x['score']) for x in st]} ✔")

print("\n圈數／擲骰測試全部通過 ✔")
