# -*- coding: utf-8 -*-
"""德州撲克連線流程測試（需先啟動 server.py）。"""
import asyncio, json
from ws_test_util import (URL, connect, recv_until, collect, drain,
                          send, make_room, close_all, run)

async def main():
    print("[1] 開德州房、8 人加入")
    conns = []
    w0 = await connect(); conns.append(w0)
    await w0.send(json.dumps({"t": "create", "name": "P0", "game_type": "poker"}))
    j = await recv_until(w0, {"joined"})
    assert j and j["game_type"] == "poker", j
    code = j["code"]
    room = await recv_until(w0, {"room"})
    assert room["max_seats"] == 8 and room["min_players"] == 2, room
    print(f"    房號 {code}｜最多 {room['max_seats']} 人｜最少 {room['min_players']} 人開局 ✔")

    for i in range(1, 8):
        w = await connect(); conns.append(w)
        await w.send(json.dumps({"t": "join", "code": code, "name": f"P{i}"}))
        jj = await recv_until(w, {"joined"})
        assert jj, f"P{i} 加入失敗"
    print("    8 人入座 ✔")

    # 第 9 人應被擋
    w9 = await connect()
    await w9.send(json.dumps({"t": "join", "code": code, "name": "P8"}))
    e = await recv_until(w9, {"error"}, timeout=2)
    assert e and "已滿" in e["msg"], e
    print(f"    第 9 人被擋：{e['msg']} ✔")
    await w9.close()

    print("\n[2] 設定大小盲")
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "set_config", "small_blind": 25,
                              "big_blind": 50, "start_stack": 2000}))
    room = await recv_until(w0, {"room"})
    cfg = room["config"]
    assert (cfg["small_blind"], cfg["big_blind"], cfg["start_stack"]) == (25, 50, 2000), cfg
    print(f"    小盲 {cfg['small_blind']}／大盲 {cfg['big_blind']}／起始籌碼 {cfg['start_stack']} ✔")

    print("\n[3] 開局：發底牌、盲注、輪到誰")
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "start"}))
    st = await recv_until(w0, {"state"})
    assert st and st["game_type"] == "poker", st
    pub, pri = st["public"], st["private"]
    assert len(pri["hole"]) == 2, pri
    assert pub["pot"] == 25 + 50, pub["pot"]
    assert pub["phase"] == "preflop"
    print(f"    底牌 {pri['hole']}｜底池 {pub['pot']}｜階段 {pub['phase']}｜"
          f"輪到座位 {pub['to_act']} ✔")

    # 底牌保密：每個人拿到的 hole 不同，且公開狀態不含別人底牌
    assert all("hole" not in p for p in pub["players"]), "公開狀態不該含底牌"
    print("    公開狀態不含任何人的底牌 ✔")

    print("\n[4] 打完一手：每個人輪到就跟注／過牌，跑到攤牌")
    done = asyncio.Event()
    box = {}

    async def player(i, ws):
        """輪到自己就做合法動作，直到本手結束。"""
        while not done.is_set():
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
            except Exception:
                return
            if m.get("t") != "state":
                continue
            pub, pri = m["public"], m["private"]
            if pub["phase"] == "over":
                if not done.is_set():
                    box["final"] = pub
                    done.set()
                return
            if pub.get("to_act") != i:
                continue
            acts = pri.get("actions") or {}
            if "check" in acts:
                a = "check"
            elif "call" in acts:
                a = "call"
            else:
                a = "fold"
            await ws.send(json.dumps({"t": "poker_act", "action": a}))

    tasks = [asyncio.create_task(player(i, conns[i])) for i in range(8)]
    try:
        await asyncio.wait_for(done.wait(), timeout=25)
    except asyncio.TimeoutError:
        print("    ！超時，可能卡住")
    for t in tasks:
        t.cancel()

    fp = box.get("final")
    assert fp, "本手應該打完"
    res = fp["result"]
    total = sum(p["stack"] for p in fp["players"])
    assert total == 8 * 2000, f"籌碼總量應為 {8*2000}，實得 {total}"
    print(f"    階段={fp['phase']}｜公牌 {fp['board']}｜結果={res['type']}")
    print(f"    贏家座位 {res['winners']}｜派彩 {res['payouts']}")
    if res["type"] == "showdown":
        for s, info in res["shown"].items():
            print(f"      座位{s}: {info['hole']} → {info['desc']}")
    print(f"    籌碼守恆（總計 {total}）✔")

    print("\n[5] 開下一手")
    for w in conns:
        await drain(w)
    await w0.send(json.dumps({"t": "next"}))
    st = await recv_until(w0, {"state"}, timeout=4)
    assert st and st["public"]["phase"] == "preflop", st
    assert st["public"]["hand_no"] == 2, st["public"]["hand_no"]
    print(f"    第 {st['public']['hand_no']} 手開始，莊家鈕在座位 {st['public']['button']} ✔")

    for w in conns:
        await w.close()
    print("\n德州撲克連線流程測試通過 ✔")


if __name__ == "__main__":
    run(main)
