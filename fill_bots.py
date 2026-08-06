# -*- coding: utf-8 -*-
"""
把 N 個機器人加入既有房間，自動摸打（讓真人用瀏覽器同桌測試/遊玩）。
用法：  python fill_bots.py <房號> [人數，預設3]
機器人策略：能胡就胡，反應多半過牌，輪到自己隨機打一張。
"""
import asyncio, json, random, sys
import websockets

URL = "ws://localhost:8080/ws"


async def bot(name, code, seed):
    rng = random.Random(seed)
    ws = await websockets.connect(URL)
    await ws.send(json.dumps({"t": "join", "code": code, "name": name}))
    seat = None
    while True:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
        t = m.get("t")
        if t == "joined":
            seat = m["seat"]
            print(f"{name} 入座 {seat}")
        elif t == "state":
            pub, pri = m["public"], m["private"]
            if pub["phase"] == "over":
                continue
            if pub["phase"] == "await_reaction" and pri["reactions"]:
                acts = pri["reactions"]
                if "hu" in acts:
                    await ws.send(json.dumps({"t": "claim", "action": "hu"}))
                else:
                    await ws.send(json.dumps({"t": "claim", "action": "pass"}))
            elif pub["phase"] == "await_discard" and pub["turn"] == seat:
                so = pri.get("self_options") or {}
                if so.get("tsumo"):
                    await ws.send(json.dumps({"t": "self", "action": "tsumo"}))
                else:
                    hand = pri.get("hand") or []
                    if hand:
                        await asyncio.sleep(0.6)  # 稍慢，像真人
                        await ws.send(json.dumps({"t": "discard", "tile": rng.choice(hand)}))
        elif t == "error":
            pass


async def main():
    code = sys.argv[1].upper()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    names = ["小華", "阿美", "老王", "阿財"]
    await asyncio.gather(*[bot(names[i], code, i + 10) for i in range(n)])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
