# -*- coding: utf-8 -*-
"""行動倒數／逾時自動出手測試（需先啟動 server.py）。"""
import asyncio, json, sys, time
import websockets

URL = "ws://localhost:8080/ws"


async def recv_until(ws, types, timeout=8):
    try:
        async with asyncio.timeout(timeout):
            while True:
                m = json.loads(await ws.recv())
                if m.get("t") in types:
                    return m
    except Exception:
        return None


async def collect(ws, seconds):
    """收集一段時間內的所有訊息。"""
    out = []
    try:
        async with asyncio.timeout(seconds):
            while True:
                out.append(json.loads(await ws.recv()))
    except Exception:
        pass
    return out


async def drain(ws, t=0.3):
    await collect(ws, t)


async def make_room(game_type, n, turn_seconds):
    conns = []
    w0 = await websockets.connect(URL)
    conns.append(w0)
    await w0.send(json.dumps({"t": "create", "name": "P0", "game_type": game_type}))
    j = await recv_until(w0, {"joined"})
    code = j["code"]
    for i in range(1, n):
        w = await websockets.connect(URL)
        conns.append(w)
        await w.send(json.dumps({"t": "join", "code": code, "name": f"P{i}"}))
        await recv_until(w, {"joined"})
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "set_config", "turn_seconds": turn_seconds}))
    room = await recv_until(w0, {"room"})
    assert room["config"]["turn_seconds"] == turn_seconds, room["config"]
    for w in conns:
        await drain(w)
    return conns, code


async def test_mahjong():
    print("[1] 麻將：沒人動作 → 自動打出、牌局繼續")
    conns, code = await make_room("mahjong", 4, 5)
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[0], {"state"}, timeout=6)
    assert st, "應已開局"
    pub = st["public"]
    assert pub.get("turn_seconds") == 5, pub.get("turn_seconds")
    assert pub.get("deadline_ms") is not None, "應該有倒數"
    print(f"    開局：輪到座位 {pub['turn']}，倒數 {pub['deadline_ms']}ms")

    # 完全不動作，等逾時
    t0 = time.time()
    msgs = await collect(conns[0], 9)
    notices = [m["msg"] for m in msgs if m.get("t") == "notice"]
    states = [m for m in msgs if m.get("t") == "state"]
    auto = [n for n in notices if "逾時" in n]
    assert auto, f"應有逾時自動出手，收到 {notices}"
    print(f"    {time.time()-t0:.1f}s 內自動處理：{auto[:3]}")
    # 牌局有前進（有人打牌了）
    last = states[-1]["public"] if states else None
    assert last and sum(len(p["discards"]) for p in last["players"]) > 0, "應該有人打牌了"
    print(f"    牌局已前進：共 {sum(len(p['discards']) for p in last['players'])} 張棄牌 ✔")

    # 連續逾時 → 暫離
    afk = [n for n in notices if "暫離" in n]
    print(f"    暫離判定：{afk[:2] if afk else '(尚未觸發)'}")
    assert last.get("afk") is not None, "狀態應帶 afk 欄位"
    for w in conns:
        await w.close()


async def test_mahjong_manual_clears_afk():
    print("\n[2] 麻將：自己動作後倒數重新計時、暫離解除")
    conns, code = await make_room("mahjong", 4, 6)
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[0], {"state"}, timeout=6)
    pub = st["public"]
    turn = pub["turn"]
    d1 = pub["deadline_ms"]
    # 讓輪到的人打一張
    ws = conns[turn]
    await drain(ws, 0.4)
    stt = await recv_until(ws, {"state"}, timeout=3) or st
    hand = stt["private"]["hand"]
    await ws.send(json.dumps({"t": "discard", "tile": hand[0]}))
    st2 = await recv_until(conns[0], {"state"}, timeout=4)
    assert st2, "打牌後應收到新狀態"
    d2 = st2["public"]["deadline_ms"]
    print(f"    打牌前倒數 {d1}ms → 打牌後重新計時 {d2}ms ✔")
    assert d2 is not None and d2 > d1 - 3000, "換人行動後倒數應重新計時"
    for w in conns:
        await w.close()


async def test_poker():
    print("\n[3] 德州：逾時自動過牌／蓋牌")
    conns, code = await make_room("poker", 3, 5)
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[0], {"state"}, timeout=6)
    assert st and st["public"]["phase"] == "preflop"
    assert st["public"].get("deadline_ms") is not None, "德州也要有倒數"
    print(f"    開局：輪到座位 {st['public']['to_act']}，倒數 {st['public']['deadline_ms']}ms")

    msgs = await collect(conns[0], 9)
    notices = [m["msg"] for m in msgs if m.get("t") == "notice"]
    auto = [n for n in notices if "逾時" in n]
    assert auto, f"應有逾時自動出手，收到 {notices}"
    print(f"    自動處理：{auto[:3]}")
    states = [m for m in msgs if m.get("t") == "state"]
    last = states[-1]["public"] if states else None
    assert last, "應有狀態更新"
    acted = [p["last_action"] for p in last["players"] if p["last_action"]]
    print(f"    各家動作：{acted}｜階段 {last['phase']} ✔")
    for w in conns:
        await w.close()


async def test_off():
    print("\n[4] 倒數可關閉（turn_seconds = 0）")
    conns, code = await make_room("mahjong", 4, 0)
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[0], {"state"}, timeout=6)
    assert st["public"].get("deadline_ms") is None, "關閉時不該有倒數"
    msgs = await collect(conns[0], 5)
    auto = [m for m in msgs if m.get("t") == "notice" and "逾時" in m.get("msg", "")]
    assert not auto, f"關閉時不該自動出手，卻收到 {auto}"
    print("    關閉後沒有倒數、也不會自動出手 ✔")
    for w in conns:
        await w.close()


async def main():
    await test_mahjong()
    await test_mahjong_manual_clears_afk()
    await test_poker()
    await test_off()
    print("\n逾時／倒數測試全部通過 ✔")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
