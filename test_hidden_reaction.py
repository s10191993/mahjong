# -*- coding: utf-8 -*-
"""
反應階段的保密測試（需先啟動 server.py）。

有人可以吃／碰／槓／胡時，「不能反應的人」不該從收到的狀態看出任何端倪
——否則光看倒數和停頓就知道別人在考慮碰牌。
"""
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


async def main():
    print("[1] 開一局，關掉倒數避免干擾")
    conns = []
    w0 = await websockets.connect(URL)
    conns.append(w0)
    await w0.send(json.dumps({"t": "create", "name": "P0"}))
    j = await recv_until(w0, {"joined"})
    code = j["code"]
    for i in range(1, 4):
        w = await websockets.connect(URL)
        conns.append(w)
        await w.send(json.dumps({"t": "join", "code": code, "name": f"P{i}"}))
        await recv_until(w, {"joined"})
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "set_config", "turn_seconds": 60}))
    await recv_until(w0, {"room"})
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "start"}))

    # 收各家的初始狀態
    states = {}
    for i, w in enumerate(conns):
        st = await recv_until(w, {"state"}, timeout=6)
        assert st, f"座位{i} 沒收到開局狀態"
        states[i] = st
    dealer = states[0]["public"]["dealer"]
    print(f"    開局完成，莊家 = 座位 {dealer}")

    print("\n[2] 想辦法打出一張「有人可以碰」的牌")
    # 找一張：某家手上有兩張一樣的，讓莊家打出那張
    hands = {i: states[i]["private"]["hand"] for i in range(4)}
    target, claimer = None, None
    for s in range(4):
        if s == dealer:
            continue
        for t in set(hands[s]):
            if hands[s].count(t) >= 2 and t in hands[dealer]:
                target, claimer = t, s
                break
        if target:
            break
    if not target:
        print("    這副牌剛好湊不出可碰的情境，跳過（隨機牌局偶爾如此）")
        for w in conns:
            await w.close()
        return

    print(f"    莊家打出 {target}；座位 {claimer} 手上有兩張，應該可以碰")
    for w in conns:
        await drain(w)
    await conns[dealer].send(json.dumps({"t": "discard", "tile": target}))

    # 收每個人打牌後的狀態
    after = {}
    for i, w in enumerate(conns):
        after[i] = await recv_until(w, {"state"}, timeout=6)

    print("\n[3] 檢查各家看到什麼")
    leaks = []
    for i in range(4):
        st = after[i]
        assert st, f"座位{i} 沒收到狀態"
        pub, pri = st["public"], st["private"]
        can_react = bool(pri.get("reactions"))
        print(f"    座位{i}: phase={pub['phase']!r:18} "
              f"deadline={pub.get('deadline_ms')} reactions={pri.get('reactions')}")
        if i == claimer:
            assert can_react, f"座位{i} 應該可以碰，卻沒收到 reactions"
            assert pub["phase"] == "await_reaction", pub["phase"]
        elif not can_react:
            # 不能反應的人：不該看到 await_reaction，也不該有倒數
            if pub["phase"] == "await_reaction":
                leaks.append(f"座位{i} 看到 phase=await_reaction")
            if pub.get("deadline_ms") is not None:
                leaks.append(f"座位{i} 看到倒數 {pub['deadline_ms']}ms")
            if "pending" in pub:
                leaks.append(f"座位{i} 看到 pending 名單")

    assert not leaks, "資訊外洩：\n  " + "\n  ".join(leaks)
    print("\n    不能反應的人：看不到 await_reaction、沒有倒數、沒有 pending ✔")

    print("\n[4] 可以反應的人自己看得到")
    st = after[claimer]
    assert "pong" in st["private"]["reactions"], st["private"]["reactions"]
    assert st["public"].get("deadline_ms") is not None, "當事人應該有倒數"
    print(f"    座位{claimer} 收到 reactions={st['private']['reactions']}、"
          f"倒數 {st['public']['deadline_ms']}ms ✔")

    for w in conns:
        await w.close()
    print("\n反應階段保密測試通過 ✔")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
