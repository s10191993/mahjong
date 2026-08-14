# -*- coding: utf-8 -*-
"""斷線重連測試（需先啟動 server.py）。"""
import asyncio, json, sys
import websockets

URL = "ws://localhost:8080/ws"


async def recv_until(ws, types, timeout=6):
    try:
        async with asyncio.timeout(timeout):
            while True:
                m = json.loads(await ws.recv())
                if m.get("t") in types:
                    return m
    except Exception:
        return None


async def drain(ws, t=0.3):
    try:
        async with asyncio.timeout(t):
            while True:
                await ws.recv()
    except Exception:
        pass


async def setup(game_type="mahjong", n=4, turn_seconds=60):
    conns, tokens = [], []
    w0 = await websockets.connect(URL)
    await w0.send(json.dumps({"t": "create", "name": "P0", "game_type": game_type}))
    j = await recv_until(w0, {"joined"})
    code = j["code"]
    conns.append(w0); tokens.append(j["token"])
    for i in range(1, n):
        w = await websockets.connect(URL)
        await w.send(json.dumps({"t": "join", "code": code, "name": f"P{i}"}))
        jj = await recv_until(w, {"joined"})
        conns.append(w); tokens.append(jj["token"])
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "set_config", "turn_seconds": turn_seconds}))
    await recv_until(w0, {"room"})
    for w in conns:
        await drain(w)
    return conns, tokens, code


async def main():
    print("[1] 牌局中斷線 → 其他人看得到「斷線」")
    conns, tokens, code = await setup()
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[0], {"state"})
    assert st, "應已開局"
    for w in conns:
        await drain(w)
    await conns[2].close()                 # 座位2 斷線
    await asyncio.sleep(0.6)
    # 讓某人動一下以觸發廣播
    room = await recv_until(conns[0], {"room"}, timeout=3)
    assert room, "應收到大廳更新"
    p2 = room["players"][2]
    assert p2 and p2["connected"] is False, f"座位2 應標記斷線，實得 {p2}"
    print(f"    座位2 斷線，其他人看到 connected=False ✔")

    print("\n[2] 重連 → 回到原座位、拿回手牌與牌桌狀態")
    w2 = await websockets.connect(URL)
    await w2.send(json.dumps({"t": "reconnect", "code": code, "token": tokens[2]}))
    j = await recv_until(w2, {"joined"})
    assert j and j["seat"] == 2, f"應回到座位2，實得 {j}"
    st2 = await recv_until(w2, {"state"}, timeout=4)
    assert st2, "重連後應立刻收到牌桌狀態"
    hand = st2["private"]["hand"]
    assert len(hand) in (16, 17), f"應拿回手牌，實得 {len(hand)} 張"
    print(f"    回到座位 {j['seat']}、手牌 {len(hand)} 張、"
          f"階段 {st2['public']['phase']} ✔")
    assert j.get("game_type") == "mahjong", j

    print("\n[3] 重連後標記回復為已連線（用牌桌狀態看，牌局中不能改設定）")
    assert st2["public"]["connected"][2] is True, st2["public"]["connected"]
    print(f"    connected={st2['public']['connected']} ✔")

    print("\n[4] 舊連線稍後才真正關閉，不可以把剛回來的人再踢掉")
    # 手機在隧道裡常是「舊連線半死不活、人已用新連線回來」，
    # 舊連線幾十秒後才關閉。模擬：再開一條連線用同一 token 重連，
    # 然後關掉「前一條」，座位必須維持已連線。
    w2b = await websockets.connect(URL)
    await w2b.send(json.dumps({"t": "reconnect", "code": code, "token": tokens[2]}))
    jb = await recv_until(w2b, {"joined"})
    assert jb and jb["seat"] == 2, jb
    await asyncio.sleep(0.4)
    try:
        await w2.close()          # 舊連線現在才關
    except Exception:
        pass
    await asyncio.sleep(0.8)
    for w in [conns[0], conns[1], conns[3], w2b]:
        await drain(w)
    # 讓輪到的人打一張以取得最新狀態
    stb = await recv_until(w2b, {"state"}, timeout=2)
    if not stb:
        await conns[0].send(json.dumps({"t": "discard", "tile": "zzz"}))
        await recv_until(conns[0], {"error"}, timeout=2)
        stb = await recv_until(w2b, {"state"}, timeout=2)
    # 用大廳訊息確認（找一個不會被牌局擋掉的觸發：座位3 開語音）
    for w in [conns[0], w2b]:
        await drain(w)
    await conns[3].send(json.dumps({"t": "voice_state", "on": True}))
    vp = await recv_until(w2b, {"voice_peers"}, timeout=3)
    assert vp is not None, "舊連線關閉後，重連者仍應收得到廣播（沒被踢掉）"
    print("    舊連線關閉後，重連者仍在線並持續收到廣播 ✔")
    await conns[3].send(json.dumps({"t": "voice_state", "on": False}))
    w2 = w2b

    print("\n[5] 德州：牌局中斷線重連，底牌還在")
    for w in [conns[0], conns[1], conns[3], w2]:
        try:
            await w.close()
        except Exception:
            pass
    pconns, ptokens, pcode = await setup("poker", 3)
    await pconns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(pconns[0], {"state"})
    assert st and st["public"]["phase"] == "preflop"
    hole_before = None
    st1 = await recv_until(pconns[1], {"state"}, timeout=4)
    if st1:
        hole_before = st1["private"]["hole"]
    for w in pconns:
        await drain(w)
    await pconns[1].close()
    await asyncio.sleep(0.6)
    w1 = await websockets.connect(URL)
    await w1.send(json.dumps({"t": "reconnect", "code": pcode, "token": ptokens[1]}))
    j = await recv_until(w1, {"joined"})
    assert j and j["seat"] == 1, j
    stp = await recv_until(w1, {"state"}, timeout=4)
    assert stp, "德州重連後應收到牌桌狀態"
    assert stp["private"]["hole"] == hole_before, \
        f"底牌應保留：{hole_before} → {stp['private']['hole']}"
    print(f"    回到座位1、底牌保留 {stp['private']['hole']} ✔")

    for w in pconns + [w1]:
        try:
            await w.close()
        except Exception:
            pass
    print("\n斷線重連測試通過 ✔")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
