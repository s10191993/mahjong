# -*- coding: utf-8 -*-
"""測試「離開房間」與「重開牌局」流程（需先啟動 server.py）。"""
import asyncio, json, sys
import websockets

URL = "ws://localhost:8080/ws"


async def recv_until(ws, types, timeout=3):
    """收訊息直到拿到指定型別之一，回傳該訊息；逾時回 None。"""
    try:
        async with asyncio.timeout(timeout):
            while True:
                m = json.loads(await ws.recv())
                if m.get("t") in types:
                    return m
    except (asyncio.TimeoutError, Exception):
        return None


async def drain(ws, t=0.25):
    try:
        async with asyncio.timeout(t):
            while True:
                await ws.recv()
    except Exception:
        pass


async def make_room(n=4):
    """開一間房並讓 n 人入座，回傳 (conns, code)。"""
    conns = []
    ws0 = await websockets.connect(URL); conns.append(ws0)
    await ws0.send(json.dumps({"t": "create", "name": "房主"}))
    m = await recv_until(ws0, {"joined"})
    code = m["code"]
    for i in range(1, n):
        w = await websockets.connect(URL); conns.append(w)
        await w.send(json.dumps({"t": "join", "code": code, "name": f"玩家{i}"}))
        await recv_until(w, {"joined"})
    for w in conns:
        await drain(w)
    return conns, code


async def test_leave_in_waiting():
    print("\n[1] 等待室離開：座位釋出、其他人看得到")
    conns, code = await make_room(4)
    await conns[2].send(json.dumps({"t": "leave"}))
    left = await recv_until(conns[2], {"left"})
    assert left, "離開者應收到 left"
    room = await recv_until(conns[0], {"room"})
    assert room, "其他人應收到 room 更新"
    occupied = sum(1 for p in room["players"] if p)
    print(f"    離開者收到 left ✔｜房內剩 {occupied} 人")
    assert occupied == 3, f"應剩 3 人，實得 {occupied}"
    for w in conns:
        await w.close()


async def test_host_leave_transfers():
    print("\n[2] 房主離開：房主自動轉移給其他人")
    conns, code = await make_room(4)
    await conns[0].send(json.dumps({"t": "leave"}))
    await recv_until(conns[0], {"left"})
    room = await recv_until(conns[1], {"room"})
    assert room, "應收到 room 更新"
    print(f"    新房主座位 = {room['host_seat']}（原為 0）")
    assert room["host_seat"] != 0, "房主應已轉移"
    assert room["players"][room["host_seat"]] is not None, "新房主必須是還在的人"
    for w in conns:
        await w.close()


async def test_leave_during_game():
    print("\n[3] 牌局中離開：本局中止，其他人回等待室")
    conns, code = await make_room(4)
    await conns[0].send(json.dumps({"t": "start"}))
    st = await recv_until(conns[1], {"state"})
    assert st, "應已開局"
    print("    已開局 ✔")
    for w in conns:
        await drain(w)
    await conns[3].send(json.dumps({"t": "leave"}))
    notice = await recv_until(conns[1], {"notice"})
    room = await recv_until(conns[1], {"room"})
    assert notice, "其他人應收到中止通知"
    assert room and room["started"] is False, "應回到未開局狀態"
    print(f"    通知：{notice['msg']}｜started={room['started']} ✔")
    for w in conns:
        await w.close()


async def test_restart():
    print("\n[4] 重開牌局：重新發牌、非房主不能按")
    conns, code = await make_room(4)
    await conns[0].send(json.dumps({"t": "start"}))
    st1 = await recv_until(conns[1], {"state"})
    hand1 = st1["private"]["hand"]
    for w in conns:
        await drain(w)

    # 非房主嘗試重開 → 應被拒
    await conns[2].send(json.dumps({"t": "restart"}))
    e = await recv_until(conns[2], {"error"}, timeout=2)
    assert e, "非房主應收到錯誤"
    print(f"    非房主被擋：{e['msg']} ✔")
    for w in conns:
        await drain(w)

    # 房主重開 → 應重新發牌
    await conns[0].send(json.dumps({"t": "restart"}))
    notice = await recv_until(conns[1], {"notice"})
    st2 = await recv_until(conns[1], {"state"})
    assert notice and st2, "應收到通知與新牌局"
    hand2 = st2["private"]["hand"]
    assert len(hand2) == 16, f"重開後手牌應 16 張，實得 {len(hand2)}"
    print(f"    通知：{notice['msg']}｜新手牌 {len(hand2)} 張、與原手牌不同={hand1 != hand2} ✔")
    for w in conns:
        await w.close()


async def test_all_leave_closes_room():
    print("\n[5] 全部離開：房間自動回收")
    conns, code = await make_room(2)
    for w in conns:
        await w.send(json.dumps({"t": "leave"}))
        await recv_until(w, {"left"})
    # 再嘗試加入該房應失敗
    w = await websockets.connect(URL)
    await w.send(json.dumps({"t": "join", "code": code, "name": "路人"}))
    e = await recv_until(w, {"error"}, timeout=2)
    assert e, "房間應已不存在"
    print(f"    房間已回收：{e['msg']} ✔")
    await w.close()
    for c in conns:
        await c.close()


async def main():
    await test_leave_in_waiting()
    await test_host_leave_transfers()
    await test_leave_during_game()
    await test_restart()
    await test_all_leave_closes_room()
    print("\n離開／重開流程測試全部通過 ✔")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
