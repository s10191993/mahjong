# -*- coding: utf-8 -*-
"""
反應優先權測試：有人能「吃」、同時別家能「碰／槓／胡」時，牌局要正確進行。

規則：胡 > 槓 > 碰 > 吃。重點不只是誰贏，而是「時序」——
先按吃的人不可以搶先執行，必須等所有有反應權的人都回覆才結算。
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import game as G
import mahjong as mj


# 一堆湊不成面子的廢牌：同花色間距都是 1（不成順、也不符十六不搭的間距≥3）
JUNK = ["m1", "m2", "m4", "m5", "m7", "m8",
        "s1", "s2", "s4", "s5", "s7", "s8", "we", "ws", "ww", "wn"]


def junk(n):
    return JUNK[:n]


def make_game():
    """做一個可控的局面：座位 0 要打 p3，座位 1 能吃、座位 2 能碰。"""
    g = G.Game(dealer=0, seed=1)
    g.wall = ["m9"] * 40          # 牌牆給足，避免流局
    for p in g.players:
        p.hand, p.melds, p.flowers, p.discards = [], [], [], []
    # 座位 0：17 張（含要打的 p3）
    g.players[0].hand = mj.sort_hand(["p3"] + junk(16))
    # 座位 1（下家）：p1 p2 → 可吃 p3
    g.players[1].hand = mj.sort_hand(["p1", "p2"] + junk(14))
    # 座位 2（對家）：兩張 p3 → 可碰
    g.players[2].hand = mj.sort_hand(["p3", "p3"] + junk(14))
    # 座位 3：什麼都不能做
    g.players[3].hand = mj.sort_hand(junk(16))
    g.turn = 0
    g.phase = "await_discard"
    # 前提檢查：除了設計好的吃／碰，不該有人能胡
    for s in (1, 2, 3):
        assert not mj.can_win(g.players[s].hand + ["p3"], 0), f"座位{s} 不該能胡 p3"
    return g


def test_pong_beats_chow_chow_first():
    print("[1] 吃的人先按 → 不可以搶先執行，碰的人按了才結算（碰贏）")
    g = make_game()
    g.discard(0, "p3")
    assert g.phase == "await_reaction", g.phase
    assert set(g.pending) == {1, 2}, g.pending
    assert "chow" in g.pending[1] and "pong" in g.pending[2]
    print(f"    反應清單：座位1={g.pending[1]}　座位2={g.pending[2]}")

    # 吃的人先按
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.phase == "await_reaction", "吃的人先按不可以馬上執行，要等碰的人"
    assert not g.players[1].melds, "還沒結算就不該有吃的面子"
    print("    座位1 先按吃 → 仍停在 await_reaction，等座位2 ✔")

    # 碰的人後按
    assert g.claim(2, "pong") is True
    assert g.phase == "await_discard", g.phase
    assert g.turn == 2, f"碰完應輪到座位2 出牌，實得 {g.turn}"
    assert [m.kind for m in g.players[2].melds] == ["pong"]
    assert not g.players[1].melds, "碰贏吃，座位1 不該吃到"
    assert g.players[0].discards == [], "被碰走的牌要從棄牌堆移除"
    assert len(g.players[2].hand) == 14, f"碰掉兩張，暗手應剩 14：{len(g.players[2].hand)}"
    print(f"    結果：座位2 碰成功、輪到座位2 出牌、座位1 沒吃到 ✔")


def test_pong_beats_chow_pong_first():
    print("\n[2] 碰的人先按 → 仍要等吃的人回覆才結算（碰贏）")
    g = make_game()
    g.discard(0, "p3")
    assert g.claim(2, "pong") is True
    assert g.phase == "await_reaction", "只有碰的人回覆，還要等吃的人"
    assert not g.players[2].melds
    print("    座位2 先按碰 → 仍停在 await_reaction ✔")
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.phase == "await_discard" and g.turn == 2
    assert [m.kind for m in g.players[2].melds] == ["pong"]
    print("    兩家都回覆後結算：碰贏 ✔")


def test_chow_wins_when_pong_passes():
    print("\n[3] 能碰的人選擇「過」 → 吃的人正常吃到")
    g = make_game()
    g.discard(0, "p3")
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.claim(2, "pass") is True
    assert g.phase == "await_discard", g.phase
    assert g.turn == 1, f"吃完應輪到座位1 出牌，實得 {g.turn}"
    m = g.players[1].melds[0]
    assert m.kind == "chow" and m.claimed == "p3", (m.kind, m.claimed)
    assert sorted(m.tiles) == ["p1", "p2", "p3"], m.tiles
    assert not g.players[2].melds
    print(f"    座位1 吃到 {m.tiles}（吃進的是 {m.claimed}）、輪到座位1 ✔")


def test_both_pass_advances_turn():
    print("\n[4] 兩家都過 → 下家正常摸牌")
    g = make_game()
    g.discard(0, "p3")
    assert g.claim(1, "pass") is True
    assert g.claim(2, "pass") is True
    assert g.phase == "await_discard", g.phase
    assert g.turn == 1, g.turn
    assert g.players[0].discards == ["p3"], "沒人要就留在棄牌堆"
    assert len(g.players[1].hand) == 17, f"摸完應有 17 張：{len(g.players[1].hand)}"
    print("    沒人要 → 座位1 摸牌、p3 留在座位0 的河裡 ✔")


def test_kong_beats_chow():
    print("\n[5] 吃 vs 明槓 → 槓贏")
    g = make_game()
    g.players[2].hand = mj.sort_hand(["p3"] * 3 + junk(13))
    g.discard(0, "p3")
    assert set(g.pending) == {1, 2}
    assert "kong" in g.pending[2] and "pong" in g.pending[2]
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.phase == "await_reaction"
    assert g.claim(2, "kong") is True
    assert [m.kind for m in g.players[2].melds] == ["kong"]
    assert g.turn == 2 and g.phase == "await_discard"
    assert not g.players[1].melds, "槓贏吃"
    print("    座位2 明槓成功（含槓後補牌）、座位1 沒吃到 ✔")


def test_hu_beats_chow_and_pong():
    print("\n[6] 吃 vs 碰 vs 胡 → 胡最大")
    g = make_game()
    # 座位 3 聽 p3（16 張聽牌，p3 進來成胡）
    g.players[3].hand = mj.sort_hand(["p1", "p2"] + ["m5"] * 3 + ["m6"] * 3
                                     + ["m7"] * 3 + ["s5"] * 3 + ["dz"] * 2)
    assert mj.can_win(g.players[3].hand + ["p3"], 0), "測試前提：座位3 要能胡 p3"
    g.discard(0, "p3")
    assert set(g.pending) == {1, 2, 3}, g.pending
    assert "hu" in g.pending[3]
    # 吃、碰都先按
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.claim(2, "pong") is True
    assert g.phase == "await_reaction", "還沒等到能胡的人回覆，不可以結算"
    print("    吃、碰都按了但還沒結算（在等能胡的人）✔")
    assert g.claim(3, "hu") is True
    assert g.phase == "over", g.phase
    seats = [w["seat"] for w in g.result["winners"]]
    assert seats == [3], seats
    assert g.result["discarder"] == 0 and g.result["win_tile"] == "p3"
    assert not g.players[1].melds and not g.players[2].melds
    print(f"    座位3 胡牌收場（座位0 放槍 p3），吃碰都不成立 ✔")


def test_chow_only_downstream():
    print("\n[7] 非下家不能吃（同樣有 p1p2 也不給吃）")
    g = make_game()
    g.players[2].hand = mj.sort_hand(["p1", "p2"] + junk(14))
    g.discard(0, "p3")
    assert 2 not in g.pending, f"座位2 不是下家，不該能吃：{g.pending}"
    assert "chow" in g.pending[1]
    assert g.claim(2, "chow", ["p1", "p2"]) is False, "非下家的吃要被拒絕"
    print("    只有座位1（下家）能吃，座位2 的吃被拒絕 ✔")


def test_illegal_claim_rejected():
    print("\n[8] 亂送不合法的動作要被擋掉，且不影響結算")
    g = make_game()
    g.discard(0, "p3")
    assert g.claim(1, "pong") is False, "座位1 沒有兩張 p3，不該能碰"
    assert g.claim(2, "chow", ["p1", "p2"]) is False, "座位2 不是下家"
    assert g.claim(3, "pass") is False, "座位3 沒有反應權，不該能回覆"
    assert g.phase == "await_reaction", "被拒絕的動作不可以推進牌局"
    assert len(g.responses) == 0, g.responses
    # 合法動作照常
    assert g.claim(1, "chow", ["p1", "p2"]) is True
    assert g.claim(2, "pong") is True
    assert g.turn == 2
    print("    三種不合法動作都被拒絕，之後正常結算 ✔")


def main():
    test_pong_beats_chow_chow_first()
    test_pong_beats_chow_pong_first()
    test_chow_wins_when_pong_passes()
    test_both_pass_advances_turn()
    test_kong_beats_chow()
    test_hu_beats_chow_and_pong()
    test_chow_only_downstream()
    test_illegal_claim_rejected()
    print("\n全部通過 ✔")


if __name__ == "__main__":
    main()
