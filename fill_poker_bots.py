# -*- coding: utf-8 -*-
"""
把 N 個機器人加入既有的德州房間，自動跟注／過牌（讓真人用瀏覽器同桌測試）。
用法：  python fill_poker_bots.py <房號> [人數，預設2]
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
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
        except asyncio.TimeoutError:
            continue
        except Exception:
            break
        t = m.get("t")
        if t == "joined":
            seat = m["seat"]
            print(f"{name} 入座 {seat}")
        elif t == "state" and m.get("game_type") == "poker":
            pub, pri = m["public"], m["private"]
            if pub["phase"] == "over" or pub.get("to_act") != seat:
                continue
            acts = pri.get("actions") or {}
            if not acts:
                continue
            await asyncio.sleep(0.6)          # 稍慢，像真人思考
            r = rng.random()
            if "check" in acts and r < 0.75:
                a, amt = "check", None
            elif "call" in acts and r < 0.8:
                a, amt = "call", None
            elif acts.get("raise") and r < 0.9:
                rr = acts["raise"]
                a, amt = "raise", min(rr["max"], rr["min"])
            elif "check" in acts:
                a, amt = "check", None
            elif "call" in acts:
                a, amt = "call", None
            else:
                a, amt = "fold", None
            await ws.send(json.dumps({"t": "poker_act", "action": a, "amount": amt}))


async def main():
    code = sys.argv[1].upper()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    names = ["阿龍", "小美", "老K", "阿財", "小黑", "阿桃", "大熊"]
    await asyncio.gather(*[bot(names[i], code, i + 5) for i in range(n)])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
