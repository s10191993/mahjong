# -*- coding: utf-8 -*-
"""
語音信令測試（需先啟動 server.py）。

只測伺服器負責的部分：誰開了語音、offer/answer/ICE 有沒有正確送到對的人、
以及不同房間之間不會互相看到。實際音訊走 WebRTC 點對點，不經過伺服器。
"""
import asyncio, json
from ws_test_util import (URL, connect, recv_until, collect, drain,
                          send, make_room, close_all, run)

async def main():
    print("[1] 開語音 → 全房收到名單")
    conns, _, code = await make_room(n=3)
    await conns[0].send(json.dumps({"t": "voice_state", "on": True}))
    for i in (1, 2):
        m = await recv_until(conns[i], {"voice_peers"})
        assert m and m["peers"] == [0], f"座位{i} 應收到 [0]，實得 {m}"
    print("    座位0 開語音，其他人都收到 peers=[0] ✔")

    for w in conns:
        await drain(w)          # 清掉上一步的廣播，才不會讀到舊名單
    await conns[1].send(json.dumps({"t": "voice_state", "on": True}))
    m = await recv_until(conns[0], {"voice_peers"})
    assert m and sorted(m["peers"]) == [0, 1], m
    print(f"    座位1 也開，名單變 {sorted(m['peers'])} ✔")

    print("\n[2] offer / answer / ICE 正確送到對方，且 from 由伺服器填")
    for w in conns:
        await drain(w)
    fake_sdp = {"type": "offer", "sdp": "v=0\r\n...test..."}
    # 座位0 發 offer 給座位1，並偽造 from 想冒充座位2
    await conns[0].send(json.dumps({"t": "rtc", "to": 1, "kind": "offer",
                                    "data": fake_sdp, "from": 2}))
    m = await recv_until(conns[1], {"rtc"})
    assert m, "座位1 應收到 rtc"
    assert m["kind"] == "offer" and m["data"] == fake_sdp, m
    assert m["from"] == 0, f"from 應由伺服器填為 0（不能被偽造成 2），實得 {m['from']}"
    print(f"    offer 送達座位1，from={m['from']}（偽造的 from=2 被忽略）✔")

    # 座位1 回 answer
    await conns[1].send(json.dumps({"t": "rtc", "to": 0, "kind": "answer",
                                    "data": {"type": "answer", "sdp": "x"}}))
    m = await recv_until(conns[0], {"rtc"})
    assert m and m["kind"] == "answer" and m["from"] == 1, m
    print(f"    answer 回到座位0，from={m['from']} ✔")

    # ICE
    await conns[0].send(json.dumps({"t": "rtc", "to": 1, "kind": "ice",
                                    "data": {"candidate": "cand"}}))
    m = await recv_until(conns[1], {"rtc"})
    assert m and m["kind"] == "ice", m
    print("    ICE candidate 送達 ✔")

    print("\n[3] 不會送到沒指定的人")
    for w in conns:
        await drain(w)
    await conns[0].send(json.dumps({"t": "rtc", "to": 1, "kind": "ice",
                                    "data": {"candidate": "only-for-1"}}))
    got1 = await recv_until(conns[1], {"rtc"}, timeout=2)
    got2 = await recv_until(conns[2], {"rtc"}, timeout=1.2)
    assert got1 and not got2, f"座位2 不該收到（got2={got2}）"
    print("    只送給指定座位，第三人收不到 ✔")

    print("\n[4] 跨房間不會互通")
    conns2, _, code2 = await make_room(n=2)
    for w in conns + conns2:
        await drain(w)
    await conns2[0].send(json.dumps({"t": "voice_state", "on": True}))
    # 另一間房開語音，第一間房不該收到
    other = await recv_until(conns[0], {"voice_peers"}, timeout=1.5)
    assert other is None, f"跨房間不該收到語音名單，實得 {other}"
    print("    A 房收不到 B 房的語音事件 ✔")

    print("\n[5] 離開語音 → 名單移除")
    for w in conns:
        await drain(w)
    await conns[0].send(json.dumps({"t": "voice_state", "on": False}))
    m = await recv_until(conns[1], {"voice_peers"})
    assert m and 0 not in m["peers"], m
    print(f"    座位0 關閉後名單為 {m['peers']} ✔")

    print("\n[6] 斷線自動退出語音")
    for w in conns[1:]:
        await drain(w)          # 清掉上一步的廣播
    await conns[1].close()
    await asyncio.sleep(0.5)
    m = await recv_until(conns[2], {"voice_peers"}, timeout=3)
    assert m and 1 not in m["peers"], f"斷線者應移出語音名單，實得 {m}"
    print(f"    座位1 斷線後名單為 {m['peers']} ✔")

    for w in conns + conns2:
        try:
            await w.close()
        except Exception:
            pass
    print("\n語音信令測試全部通過 ✔")


if __name__ == "__main__":
    run(main)
