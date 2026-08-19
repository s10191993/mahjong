# -*- coding: utf-8 -*-
"""
連線測試的共用工具。

以前每個 test_*.py 都自己複製一份 recv_until / drain / make_room，而且把
ws://localhost:8080 寫死。複製久了會走味——test_timeout.py 就曾因為自己那份
對「反應階段遮罩」的假設過時而變成機率性失敗。這裡收成單一來源，
順便讓網址可由環境變數指定，run_tests.py 才能開在隨機埠上跑。
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from typing import Iterable, NamedTuple

import websockets

#: 測試對象；run_tests.py 會設成自己起的臨時伺服器
URL = os.environ.get("MJ_TEST_URL", "ws://localhost:8080/ws")


def use_utf8_stdout():
    """Windows 主控台預設 cp950，印 ✔ 或中文會炸。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run(main_coro_fn):
    """測試檔的統一進入點：修好 stdout 編碼再跑 async main。"""
    use_utf8_stdout()
    asyncio.run(main_coro_fn())


# ---- 單一連線的收送 --------------------------------------------------------
async def connect():
    return await websockets.connect(URL)


async def recv_until(ws, types: Iterable[str], timeout: float = 6):
    """收到指定型別的訊息就回傳；逾時回 None（測試自己判斷是不是預期）。"""
    types = set(types)
    try:
        async with asyncio.timeout(timeout):
            while True:
                m = json.loads(await ws.recv())
                if m.get("t") in types:
                    return m
    except Exception:
        return None


async def collect(ws, seconds: float) -> list[dict]:
    """收集一段時間內的所有訊息（用來看逾時、廣播這類非同步事件）。"""
    out = []
    try:
        async with asyncio.timeout(seconds):
            while True:
                out.append(json.loads(await ws.recv()))
    except Exception:
        pass
    return out


async def drain(ws, t: float = 0.3):
    """丟掉排隊中的舊訊息。

    很多測試的偶發失敗都是「讀到上一次廣播」造成的，動作前先清乾淨。
    """
    await collect(ws, t)


async def send(ws, **payload):
    await ws.send(json.dumps(payload))


async def states(ws, seconds: float = 1.0) -> list[dict]:
    """收一段時間，只挑出 state 訊息（要看最終狀態就取 [-1]）。"""
    return [m for m in await collect(ws, seconds) if m.get("t") == "state"]


# ---- 開房 ------------------------------------------------------------------
class Table(NamedTuple):
    conns: list          # 每個座位一條 WebSocket
    tokens: list[str]    # 重連用的 token，順序同 conns
    code: str            # 房號


async def make_room(game_type: str = "mahjong", n: int = 4,
                    turn_seconds: int | None = None,
                    names: list[str] | None = None) -> Table:
    """開一間房、讓 n 個人入座，回傳 (conns, tokens, code)。

    turn_seconds 給了才會送 set_config——不給就沿用伺服器預設，
    避免測試無意間改到不相關的設定。
    """
    conns, tokens = [], []
    name_of = (lambda i: names[i]) if names else (lambda i: f"P{i}")

    w0 = await connect()
    await send(w0, t="create", name=name_of(0), game_type=game_type)
    j = await recv_until(w0, {"joined"})
    assert j, "開房失敗：沒收到 joined（伺服器沒開？）"
    code = j["code"]
    conns.append(w0)
    tokens.append(j["token"])

    for i in range(1, n):
        w = await connect()
        await send(w, t="join", code=code, name=name_of(i))
        jj = await recv_until(w, {"joined"})
        assert jj, f"座位{i} 加入失敗"
        conns.append(w)
        tokens.append(jj["token"])

    for w in conns:
        await drain(w)

    if turn_seconds is not None:
        await send(w0, t="set_config", turn_seconds=turn_seconds)
        room = await recv_until(w0, {"room"})
        assert room and room["config"]["turn_seconds"] == turn_seconds, room
        for w in conns:
            await drain(w)

    return Table(conns, tokens, code)


async def start(table: Table, timeout: float = 6) -> dict[int, dict]:
    """房主開局，回傳每個座位收到的第一個 state。"""
    await send(table.conns[0], t="start")
    out = {}
    for i, w in enumerate(table.conns):
        st = await recv_until(w, {"state"}, timeout=timeout)
        assert st, f"座位{i} 沒收到開局狀態"
        out[i] = st
    return out


async def close_all(conns):
    for w in conns:
        try:
            await w.close()
        except Exception:
            pass
