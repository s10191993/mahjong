# -*- coding: utf-8 -*-
"""
連線層的反應優先權測試（需先啟動 server.py）。

情境：下家能「吃」、另一家能「碰」，同一張牌。
要驗證的不只是誰贏，而是牌局會不會卡住：
  [A] 吃的人先按 → 不會馬上執行，等碰的人按了才結算，且碰贏
  [B] 能碰的人完全不回應（發呆／斷線）→ 逾時自動過，吃的人正常吃到、牌局繼續
  [C] 吃的人看不出「有別人也在考慮碰」
"""
import asyncio, json
import mahjong as mj
from ws_test_util import (URL, connect, recv_until, collect, drain,
                          send, make_room, close_all, run)

async def deal_until_chow_vs_pong(conns, max_tries=40):
    """一直重新發牌，直到出現「下家能吃、另一家能碰同一張」的局面。

    回傳 (打牌者, 要打的牌, 能吃的座位, 能碰的座位)。
    """
    for attempt in range(max_tries):
        await conns[0].send(json.dumps({"t": "start" if attempt == 0 else "restart"}))
        states = {}
        for i, w in enumerate(conns):
            st = await recv_until(w, {"state"}, timeout=6)
            if not st:
                return None
            states[i] = st
        pub = states[0]["public"]
        if pub["phase"] != "await_discard":
            continue
        dealer = pub["turn"]
        hands = {i: states[i]["private"]["hand"] for i in range(4)}
        down = (dealer + 1) % 4
        for t in sorted(set(hands[dealer])):
            if mj.is_flower(t):
                continue
            if not mj.chow_options(hands[down], t):
                continue
            ponger = next((s for s in range(4)
                           if s not in (dealer, down) and hands[s].count(t) >= 2), None)
            if ponger is None:
                continue
            # 不能有人胡這張，否則牌局直接結束、測不到吃碰
            if any(mj.can_win(hands[s] + [t], 0) for s in range(4) if s != dealer):
                continue
            print(f"    第 {attempt + 1} 副牌湊到情境："
                  f"座位{dealer} 打 {t}，座位{down} 能吃、座位{ponger} 能碰")
            return dealer, t, down, ponger
    return None


async def test_chow_then_pong():
    print("[A] 吃的人先按，碰的人後按 → 碰贏，牌局繼續")
    conns, _, code = await make_room(turn_seconds=60)          # 倒數拉長，先不讓逾時介入
    found = await deal_until_chow_vs_pong(conns)
    assert found, "40 副牌都沒湊到吃碰同張的情境"
    dealer, tile, chower, ponger = found

    for w in conns:
        await drain(w)
    await conns[dealer].send(json.dumps({"t": "discard", "tile": tile}))
    after = {i: await recv_until(w, {"state"}, timeout=6) for i, w in enumerate(conns)}

    assert "chow" in after[chower]["private"]["reactions"], after[chower]["private"]["reactions"]
    assert "pong" in after[ponger]["private"]["reactions"], after[ponger]["private"]["reactions"]
    print(f"    座位{chower} 收到 {after[chower]['private']['reactions']}、"
          f"座位{ponger} 收到 {after[ponger]['private']['reactions']}")

    # [C] 吃的人不該看出有別人在考慮碰
    pub_c = after[chower]["public"]
    assert "pending" not in pub_c, "外洩：吃的人看得到 pending 名單"
    assert not any(k for k in pub_c if "react" in k.lower() and k != "phase"), \
        f"外洩：public 有反應相關欄位 {list(pub_c)}"
    print("    吃的人看不到誰要碰（沒有 pending／反應名單）✔")

    # 吃的人先按 → 不可以馬上執行
    opts = mj.chow_options(after[chower]["private"]["hand"], tile)
    await conns[chower].send(json.dumps({"t": "claim", "action": "chow",
                                         "tiles": list(opts[0])}))
    await asyncio.sleep(0.8)
    msgs = await collect(conns[chower], 0.6)
    sts = [m for m in msgs if m.get("t") == "state"]
    if sts:
        assert sts[-1]["public"]["phase"] == "await_reaction", \
            f"吃的人先按就結算了：{sts[-1]['public']['phase']}"
    print("    座位%d 按吃後牌局沒有推進，還在等座位%d ✔" % (chower, ponger))

    # 碰的人後按（先清掉排隊中的舊狀態，否則會讀到吃那一刻的廣播）
    await drain(conns[ponger], 0.4)
    await conns[ponger].send(json.dumps({"t": "claim", "action": "pong"}))
    sts = [m for m in await collect(conns[ponger], 1.5) if m.get("t") == "state"]
    assert sts, "碰之後應收到狀態"
    pub = sts[-1]["public"]
    assert pub["phase"] == "await_discard", pub["phase"]
    assert pub["turn"] == ponger, f"碰完應輪到座位{ponger}，實得 {pub['turn']}"
    kinds = [m["kind"] for m in pub["players"][ponger]["melds"]]
    assert "pong" in kinds, kinds
    assert not pub["players"][chower]["melds"], "碰贏吃，吃的人不該有面子"
    print(f"    結算：座位{ponger} 碰成功、輪到他出牌、座位{chower} 沒吃到 ✔")

    for w in conns:
        await w.close()


async def test_pong_player_never_responds():
    print("\n[B] 能碰的人完全不回應 → 逾時自動過，吃的人正常吃到")
    conns, _, code = await make_room(turn_seconds=5)           # 短倒數，逼出逾時
    found = await deal_until_chow_vs_pong(conns)
    assert found, "40 副牌都沒湊到吃碰同張的情境"
    dealer, tile, chower, ponger = found

    for w in conns:
        await drain(w)
    await conns[dealer].send(json.dumps({"t": "discard", "tile": tile}))
    st = await recv_until(conns[chower], {"state"}, timeout=6)
    opts = mj.chow_options(st["private"]["hand"], tile)
    await conns[chower].send(json.dumps({"t": "claim", "action": "chow",
                                         "tiles": list(opts[0])}))
    print(f"    座位{chower} 按了吃，座位{ponger} 裝死不回應…")

    # 等逾時把碰的人自動帶過
    msgs = await collect(conns[chower], 9)
    sts = [m for m in msgs if m.get("t") == "state"]
    assert sts, "逾時後應該要有新狀態，牌局不能卡死"
    pub = sts[-1]["public"]
    assert pub["phase"] != "await_reaction", f"牌局卡在反應階段：{pub['phase']}"
    kinds = [m["kind"] for m in pub["players"][chower]["melds"]]
    assert "chow" in kinds, f"逾時自動過之後，吃應該成立：{kinds}"
    assert not pub["players"][ponger]["melds"], "沒按碰的人不該拿到碰"
    notices = [m["msg"] for m in msgs if m.get("t") == "notice"]
    print(f"    逾時通知：{[n for n in notices if '逾時' in n][:2]}")
    print(f"    座位{chower} 成功吃到、牌局繼續（phase={pub['phase']}、"
          f"輪到座位{pub['turn']}）✔")

    for w in conns:
        await w.close()


async def main():
    await test_chow_then_pong()
    await test_pong_player_never_responds()
    print("\n連線層優先權測試通過 ✔")


if __name__ == "__main__":
    run(main)
