# -*- coding: utf-8 -*-
"""
德州「秀牌」與「補碼」的連線層測試。

這兩個訊息型別原本只有引擎有測、伺服器分支完全沒測——
改壞了不會有人發現，補上。
"""
import json

from ws_test_util import (recv_until, collect, drain, send, make_room,
                          close_all, run)


async def last_state(ws, seconds=1.2):
    sts = [m for m in await collect(ws, seconds) if m.get("t") == "state"]
    return sts[-1] if sts else None


async def play_until_fold_win(conns, max_hands=12):
    """一直開新手，直到出現「其他人全蓋、贏家沒攤牌」的局面。

    回傳 (贏家座位, 該座位收到的 state)。
    """
    for hand in range(max_hands):
        await send(conns[0], t="start" if hand == 0 else "next")
        st = await recv_until(conns[0], {"state"}, timeout=5)
        if not st:
            return None
        # 除了第一個還能行動的人以外，其他人全蓋
        for _ in range(30):
            pub = st["public"]
            if pub["phase"] == "over":
                break
            actor = pub.get("to_act")
            if actor is None:
                break
            await drain(conns[actor], 0.15)
            await send(conns[actor], t="poker_act", action="fold")
            st = await recv_until(conns[actor], {"state"}, timeout=4) or st
            for w in conns:
                await drain(w, 0.05)
            st = await last_state(conns[0], 0.6) or st

        st = await last_state(conns[0], 0.8) or st
        res = st["public"].get("result") or {}
        if res.get("type") == "fold_win" and res.get("winners"):
            return res["winners"][0], st
    return None


async def test_show():
    print("[1] 沒攤牌就收池 → 贏家可以按秀牌，其他人看得到")
    conns, _, code = await make_room("poker", 3, turn_seconds=0)
    found = await play_until_fold_win(conns)
    assert found, "12 手都沒出現 fold_win 的局面"
    winner, st = found
    print(f"    座位{winner} 收池（沒攤牌）")

    for w in conns:
        await drain(w, 0.3)
    await send(conns[winner], t="poker_show")
    msgs = await collect(conns[1 if winner != 1 else 0], 1.5)
    notices = [m["msg"] for m in msgs if m.get("t") == "notice"]
    sts = [m for m in msgs if m.get("t") == "state"]
    assert notices, f"別家應收到秀牌通知，實得 {msgs}"
    assert sts, "秀牌後應廣播新狀態"
    shown = (sts[-1]["public"].get("result") or {}).get("shown") or {}
    assert str(winner) in shown or winner in shown, f"秀牌後別家應看到底牌：{shown}"
    print(f"    通知：{notices[0]}")
    print(f"    別家看得到贏家底牌 ✔")

    # 非贏家不能秀、贏家不能秀第二次
    other = next(i for i in range(3) if i != winner)
    await drain(conns[other], 0.2)
    await send(conns[other], t="poker_show")
    e = await recv_until(conns[other], {"error"}, timeout=2)
    assert e, "非贏家秀牌應被拒絕"
    print(f"    非贏家秀牌被拒：{e['msg']} ✔")

    await drain(conns[winner], 0.2)
    await send(conns[winner], t="poker_show")
    e = await recv_until(conns[winner], {"error"}, timeout=2)
    assert e, "重複秀牌應被拒絕"
    print(f"    重複秀牌被拒：{e['msg']} ✔")
    await close_all(conns)


async def test_rebuy():
    print("\n[2] 補碼：金額限制、時機限制都要擋")
    conns, _, code = await make_room("poker", 3, turn_seconds=0)
    await send(conns[0], t="start")
    st = await recv_until(conns[0], {"state"}, timeout=5)
    assert st, "應已開局"

    # 籌碼還很多 → 不能補
    await drain(conns[1], 0.2)
    await send(conns[1], t="rebuy", amount=500)
    e = await recv_until(conns[1], {"error"}, timeout=2)
    assert e, "籌碼充足時補碼應被拒絕"
    print(f"    籌碼充足時被拒：{e['msg']} ✔")

    # 不合法金額 → 不能補
    await drain(conns[1], 0.2)
    await send(conns[1], t="rebuy", amount=777)
    e = await recv_until(conns[1], {"error"}, timeout=2)
    assert e, "非 500/1000 的金額應被拒絕"
    print(f"    金額 777 被拒：{e['msg']} ✔")

    # 非數字不該讓伺服器炸掉
    await drain(conns[1], 0.2)
    await send(conns[1], t="rebuy", amount="很多")
    e = await recv_until(conns[1], {"error"}, timeout=2)
    assert e, "非數字金額應被擋，而不是讓伺服器出錯"
    print(f"    金額「很多」被擋住、伺服器沒掛 ✔")

    # 伺服器還活著
    await drain(conns[0], 0.2)
    await send(conns[0], t="poker_act", action="fold")
    st = await recv_until(conns[0], {"state", "error"}, timeout=3)
    assert st, "亂送金額後伺服器應仍正常回應"
    print("    後續動作仍正常 ✔")
    await close_all(conns)


async def main():
    await test_show()
    await test_rebuy()
    print("\n秀牌／補碼連線測試通過 ✔")


if __name__ == "__main__":
    run(main)
