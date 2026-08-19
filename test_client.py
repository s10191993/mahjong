# -*- coding: utf-8 -*-
"""
用 4 條 WebSocket 連線模擬四位玩家，把伺服器完整跑到一局結束。
驗證：開房/加入/開局/摸打/吃碰槓胡/結算 的通訊協定與伺服器狀態機。
需先啟動 server.py（預設 http://localhost:8080）。
"""
import asyncio, json, random
from ws_test_util import (URL, connect, recv_until, collect, drain,
                          send, make_room, close_all, run)

class Bot:
    def __init__(self, name, rng):
        self.name = name
        self.rng = rng
        self.seat = None
        self.code = None
        self.ws = None

    async def recv(self):
        return json.loads(await self.ws.recv())

    async def send(self, obj):
        await self.ws.send(json.dumps(obj))


async def run_game():
    rng = random.Random(0)
    bots = [Bot(n, random.Random(i + 1)) for i, n in enumerate(["阿明", "小華", "阿美", "老王"])]

    # 連線
    conns = []
    for b in bots:
        b.ws = await connect()
        conns.append(b.ws)

    # 座位0開房
    await bots[0].send({"t": "create", "name": bots[0].name})
    code = None
    for _ in range(5):
        m = await bots[0].recv()
        if m["t"] == "joined":
            code = m["code"]; bots[0].seat = m["seat"]; bots[0].code = code
            break
    assert code, "開房失敗"
    print(f"開房成功，房號 {code}")

    # 其餘三家加入
    for b in bots[1:]:
        await b.send({"t": "join", "code": code, "name": b.name})
        while True:
            m = await b.recv()
            if m["t"] == "joined":
                b.seat = m["seat"]; b.code = code
                break
    print("四人入座：", [(b.name, b.seat) for b in bots])

    # 清掉每個連線在 join 之後累積的 room 廣播
    async def drain(b):
        try:
            while True:
                await asyncio.wait_for(b.recv(), timeout=0.05)
        except Exception:
            pass
    for b in bots:
        await drain(b)

    # 房主開局
    await bots[0].send({"t": "start"})

    state = {b.seat: None for b in bots}
    done = asyncio.Event()
    result_holder = {}

    async def player_loop(b):
        while not done.is_set():
            try:
                m = await asyncio.wait_for(b.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if m["t"] == "error":
                # 動作被拒絕是正常的（時機不對），忽略
                continue
            if m["t"] != "state":
                continue
            pub, pri = m["public"], m["private"]
            if pub["phase"] == "over":
                if not done.is_set():
                    result_holder["result"] = pub["result"]
                    done.set()
                continue
            # 反應階段
            if pub["phase"] == "await_reaction" and pri["reactions"]:
                acts = pri["reactions"]
                if "hu" in acts:
                    await b.send({"t": "claim", "action": "hu"})
                else:
                    # 偶爾碰/吃增加覆蓋率，其餘過
                    r = b.rng.random()
                    if "pong" in acts and r < 0.3:
                        await b.send({"t": "claim", "action": "pong"})
                    elif "chow" in acts and r < 0.5:
                        opts = pri.get("chow_options") or []
                        await b.send({"t": "claim", "action": "chow",
                                      "tiles": opts[0] if opts else None})
                    else:
                        await b.send({"t": "claim", "action": "pass"})
                continue
            # 自己的回合
            if pub["phase"] == "await_discard" and pub["turn"] == b.seat:
                so = pri.get("self_options") or {}
                if so.get("tsumo"):
                    await b.send({"t": "self", "action": "tsumo"})
                    continue
                if so.get("ankong") and b.rng.random() < 0.4:
                    await b.send({"t": "self", "action": "ankong", "tile": so["ankong"][0]})
                    continue
                hand = pri.get("hand") or []
                if hand:
                    await b.send({"t": "discard", "tile": b.rng.choice(hand)})

    tasks = [asyncio.create_task(player_loop(b)) for b in bots]
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
    except asyncio.TimeoutError:
        print("！！超時，可能卡住")
        for t in tasks:
            t.cancel()
        for w in conns:
            await w.close()
        return False

    for t in tasks:
        t.cancel()
    res = result_holder.get("result", {})
    if res.get("type") == "win":
        w = res["winner"]
        print(f"結算：座位{w} 胡牌，{res['tai']} 台，"
              f"{'自摸' if res['self_draw'] else '食胡'}，明細 {res['tai_detail']}")
    else:
        print(f"結算：{res.get('type')}")
    for w in conns:
        await w.close()
    return True


async def main():
    ok = True
    for i in range(3):
        print(f"\n=== 第 {i+1} 局測試 ===")
        r = await run_game()
        ok = ok and r
    print("\n伺服器端到端測試", "通過 ✔" if ok else "有問題 �’")


if __name__ == "__main__":
    run(main)
