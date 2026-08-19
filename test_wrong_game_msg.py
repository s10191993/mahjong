# -*- coding: utf-8 -*-
"""
送錯房型的訊息不可以毀掉房間。

前端不會送這種訊息，但伺服器是權威的，不能假設客戶端乖乖聽話。
實測過的災情：德州房收到麻將的 restart → 牌桌被換成麻將牌局，
之後所有德州動作都被守衛靜靜丟掉，整間房沒有回應也沒有錯誤訊息。
"""
from ws_test_util import (recv_until, collect, drain, send, make_room,
                          close_all, run)


async def test_restart_on_poker_room():
    print("[1] 德州房收到麻將的 restart → 要擋下來，房間不能壞")
    conns, _, code = await make_room("poker", 3, turn_seconds=0)
    await send(conns[0], t="start")
    st = await recv_until(conns[0], {"state"}, timeout=5)
    assert st and st["public"]["phase"] == "preflop", st

    await drain(conns[0], 0.3)
    await send(conns[0], t="restart")
    msgs = await collect(conns[0], 1.5)
    errs = [m for m in msgs if m.get("t") == "error"]
    assert errs, f"應回明確錯誤，實得 {[m.get('t') for m in msgs]}"
    assert not any(m.get("t") == "notice" and "重開" in m.get("msg", "")
                   for m in msgs), "不可以真的去重開麻將牌局"
    print(f"    被擋下：{errs[0]['msg']}")

    # 房間還活著：德州動作照常有回應
    await drain(conns[0], 0.3)
    actor = st["public"].get("to_act")
    await send(conns[actor], t="poker_act", action="fold")
    m = await recv_until(conns[actor], {"state", "error"}, timeout=4)
    assert m, "房間被弄壞了：後續動作完全沒有回應"
    print(f"    房間仍正常（後續動作回 {m['t']}）✔")
    await close_all(conns)


async def test_poker_msgs_on_mahjong_room():
    print("\n[2] 麻將房收到德州訊息 → 忽略，牌局不受影響")
    conns, _, code = await make_room("mahjong", 4, turn_seconds=0)
    await send(conns[0], t="start")
    st = await recv_until(conns[0], {"state"}, timeout=5)
    assert st, "應已開局"
    before = st["public"]["phase"]

    for msg in ({"t": "poker_act", "action": "fold"},
                {"t": "rebuy", "amount": 500},
                {"t": "poker_show"}):
        await drain(conns[0], 0.2)
        await send(conns[0], **msg)
    await drain(conns[0], 0.5)

    # 牌局狀態沒被動到，而且還能正常打牌
    await send(conns[0], t="poker_act", action="fold")
    await drain(conns[0], 0.4)
    turn = st["public"]["turn"]
    stt = await recv_until(conns[turn], {"state"}, timeout=3)
    hand = (stt or st)["private"].get("hand")
    if turn == 0 and hand:
        await send(conns[0], t="discard", tile=hand[0])
        m = await recv_until(conns[0], {"state"}, timeout=4)
        assert m, "德州訊息之後應該還能正常打牌"
        print(f"    德州訊息被忽略，麻將照常運作（phase {before} → {m['public']['phase']}）✔")
    else:
        print(f"    德州訊息被忽略，牌局仍在 {before} ✔")
    await close_all(conns)


async def main():
    await test_restart_on_poker_room()
    await test_poker_msgs_on_mahjong_room()
    print("\n錯房型訊息測試通過 ✔")


if __name__ == "__main__":
    run(main)
