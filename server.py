# -*- coding: utf-8 -*-
"""
台灣麻將 16 張 —— 連線伺服器（aiohttp，單一程序同時提供網頁 + WebSocket）

啟動：  python server.py
然後瀏覽器開  http://localhost:8080
朋友連同一台伺服器（區網用你的內網 IP，網際網路需做埠轉發或用 ngrok 之類）。
"""
from __future__ import annotations
import asyncio
import json
import os
import random
import secrets
import string
import sys
import time

from aiohttp import web, WSMsgType

import mahjong as mj
from game import Game, SEAT_WINDS

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

DEFAULT_BASE = 100      # 預設底
DEFAULT_TAI = 20        # 預設每台
rooms: dict[str, "Room"] = {}


def roll_dice(rng: random.Random):
    """擲 3 顆骰。回傳 (點數, 加台, 是否翻倍, 牌型清單)。
    全紅(三顆都是紅點 1/4)+1台、順子(三連號)+1台、豹子(三同點)翻倍。"""
    d = [rng.randint(1, 6) for _ in range(3)]
    s = sorted(d)
    bonus, double, patterns = 0, False, []
    if all(x in (1, 4) for x in d):
        bonus += 1
        patterns.append("全紅")
    if s[0] + 1 == s[1] and s[1] + 1 == s[2]:
        bonus += 1
        patterns.append("順子")
    if s[0] == s[2]:
        double = True
        patterns.append("豹子")
    return d, bonus, double, patterns


def new_code() -> str:
    while True:
        code = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
        if code not in rooms:
            return code


class Seat:
    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token
        self.ws: web.WebSocketResponse | None = None
        self.score = 0
        self.connected = False


class Room:
    def __init__(self, code: str):
        self.code = code
        self.seats: list[Seat | None] = [None, None, None, None]
        self.host_seat = 0
        self.game: Game | None = None
        self.dealer = 0
        self.round_wind = "we"        # 由 round_index 推導，保留欄位相容
        self.dealer_streak = 0
        self.hand_no = 0
        # 可由房主設定
        self.base = DEFAULT_BASE
        self.tai_value = DEFAULT_TAI
        self.dice_rule = False
        self.rounds_target = 1        # 打幾圈：1圈 / 2圈 / 4圈(1將)
        # 局數進度
        self.round_index = 0          # 0=東圈 1=南圈 2=西圈 3=北圈
        self.start_dealer = 0         # 本圈的起莊（骰子決定）
        self.finished = False         # 整場是否已結束
        self.start_dice = None        # 決定莊家的骰子
        # 本局骰子結果
        self.dice = None            # [d1,d2,d3]
        self.dice_bonus = 0
        self.dice_double = False
        self.dice_patterns: list[str] = []
        self.rng = random.Random()
        self.last_active = time.time()      # 給房間清理用

    def touch(self):
        self.last_active = time.time()

    def anyone_connected(self) -> bool:
        return any(s and s.connected for s in self.seats)

    def reassign_host(self):
        """房主離開後，把房主交給還在的人（優先給已連線的）。"""
        if self.seats[self.host_seat] is not None:
            return
        for i, s in enumerate(self.seats):
            if s and s.connected:
                self.host_seat = i
                return
        for i, s in enumerate(self.seats):
            if s:
                self.host_seat = i
                return

    def abandon_game(self):
        """中止進行中的牌局，回到等待室（分數保留）。"""
        self.game = None
        self.dice = None
        self.dice_bonus = 0
        self.dice_double = False
        self.dice_patterns = []

    def occupied(self) -> int:
        return sum(1 for s in self.seats if s is not None)

    def find_free_seat(self) -> int | None:
        for i, s in enumerate(self.seats):
            if s is None:
                return i
        return None

    def seat_of_token(self, token: str) -> int | None:
        for i, s in enumerate(self.seats):
            if s and s.token == token:
                return i
        return None

    # ---- 廣播 ----------------------------------------------------------------
    def lobby_payload(self) -> dict:
        return {
            "t": "room",
            "code": self.code,
            "host_seat": self.host_seat,
            "started": self.game is not None,
            "config": {"base": self.base, "tai_value": self.tai_value,
                       "dice_rule": self.dice_rule, "rounds_target": self.rounds_target},
            "progress": self.progress(),
            "players": [
                None if s is None else {
                    "seat": i, "name": s.name,
                    "connected": s.connected, "score": s.score,
                }
                for i, s in enumerate(self.seats)
            ],
        }

    async def broadcast_lobby(self):
        payload = self.lobby_payload()
        await self._send_all(payload)

    async def broadcast_state(self):
        """牌局進行中：每位玩家送公開狀態 + 自己的私有狀態。"""
        if not self.game:
            return
        pub = self.game.public_state()
        # 把座位名字、分數塞進 public 方便前端顯示
        for i, sp in enumerate(pub["players"]):
            seat = self.seats[i]
            sp["name"] = seat.name if seat else f"座位{i}"
            sp["score"] = seat.score if seat else 0
            sp["wind"] = SEAT_WINDS[(i - self.game.dealer) % 4]
        # 底/台 與 骰子資訊
        pub["config"] = {"base": self.base, "tai_value": self.tai_value,
                         "dice_rule": self.dice_rule, "rounds_target": self.rounds_target}
        pub["dice"] = self.dice_info()
        pub["progress"] = self.progress()
        if self.finished:
            pub["standings"] = self.standings()
        for i, seat in enumerate(self.seats):
            if seat and seat.connected and seat.ws is not None:
                msg = {"t": "state", "public": pub, "private": self.game.private_state(i),
                       "hand_no": self.hand_no}
                await self._safe_send(seat.ws, msg)

    async def _send_all(self, payload: dict):
        for s in self.seats:
            if s and s.connected and s.ws is not None:
                await self._safe_send(s.ws, payload)

    async def _safe_send(self, ws: web.WebSocketResponse, payload: dict):
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    # ---- 開新一局 ------------------------------------------------------------
    def roll_for_dealer(self, from_seat: int = 0):
        """擲三顆骰決定莊家：從 from_seat 起算，數到點數總和那一家。"""
        d = [self.rng.randint(1, 6) for _ in range(3)]
        total = sum(d)
        dealer = (from_seat + total - 1) % 4
        self.start_dice = {"values": d, "total": total, "dealer": dealer}
        self.dealer = dealer
        self.start_dealer = dealer
        self.dealer_streak = 0
        self.round_index = 0
        self.round_wind = SEAT_WINDS[0]
        self.finished = False
        return self.start_dice

    def progress(self) -> dict:
        return {
            "round_index": self.round_index,
            "rounds_target": self.rounds_target,
            "round_wind": SEAT_WINDS[self.round_index % 4],
            "dealer": self.dealer,
            "dealer_streak": self.dealer_streak,
            "finished": self.finished,
            "start_dice": self.start_dice,
            "hand_no": self.hand_no,
        }

    def standings(self) -> list:
        return sorted(
            [{"seat": i, "name": s.name, "score": s.score}
             for i, s in enumerate(self.seats) if s],
            key=lambda x: -x["score"])

    def dice_info(self):
        if not self.dice_rule or not self.dice:
            return None
        return {"values": self.dice, "bonus": self.dice_bonus,
                "double": self.dice_double, "patterns": self.dice_patterns}

    def start_new_hand(self):
        self.hand_no += 1
        if self.dice_rule:
            self.dice, self.dice_bonus, self.dice_double, self.dice_patterns = roll_dice(self.rng)
        else:
            self.dice, self.dice_bonus, self.dice_double, self.dice_patterns = None, 0, False, []
        self.round_wind = SEAT_WINDS[self.round_index % 4]
        self.game = Game(dealer=self.dealer, round_wind=self.round_wind,
                         dealer_streak=self.dealer_streak)
        self.game.start()

    def settle(self):
        """把本局結果換算成分數。"""
        g = self.game
        if not g or not g.result:
            return
        res = g.result
        if res["type"] == "draw":
            # 流局：連莊（不換莊，圈數不推進）
            self.dealer_streak += 1
            res["progress"] = self.progress()
            return
        winners = res.get("winners") or [{"seat": res["winner"], "tai": res["tai"]}]

        def money(tai):
            eff = tai + self.dice_bonus                   # 骰規：全紅/順子 +台
            amt = self.base + eff * self.tai_value        # 底 + 台×每台
            if self.dice_double:                          # 骰規：豹子翻倍
                amt *= 2
            return eff, amt

        # 逐位贏家結算（一炮多響：放槍者付給每一位）
        for w in winners:
            eff_tai, amount = money(w["tai"])
            w["settle"] = {"eff_tai": eff_tai, "amount": amount}
            ws = w["seat"]
            if res["self_draw"]:
                for i in range(4):
                    if i != ws and self.seats[i]:
                        self.seats[i].score -= amount
                        self.seats[ws].score += amount
            else:
                loser = res["discarder"]
                if self.seats[loser] and self.seats[ws]:
                    self.seats[loser].score -= amount
                    self.seats[ws].score += amount

        # 相容欄位（單一贏家的顯示用）
        eff_tai, amount = money(res["tai"])
        res["settle"] = {
            "base": self.base, "tai_value": self.tai_value, "eff_tai": eff_tai,
            "amount": amount, "dice": self.dice_info(),
            "total_paid": sum(w["settle"]["amount"] for w in winners),
        }
        # 連莊判斷：只要莊家是贏家之一就連莊
        if any(w["seat"] == self.dealer for w in winners):
            self.dealer_streak += 1
        else:
            self._rotate_dealer()
        res["progress"] = self.progress()
        if self.finished:
            res["standings"] = self.standings()

    def _rotate_dealer(self):
        """換莊；轉回起莊表示一圈結束，圈數滿了就整場結束。"""
        self.dealer = (self.dealer + 1) % 4
        self.dealer_streak = 0
        if self.dealer == self.start_dealer:
            self.round_index += 1
            if self.round_index >= self.rounds_target:
                self.finished = True
            else:
                self.round_wind = SEAT_WINDS[self.round_index % 4]


# ---------------------------------------------------------------------------
# WebSocket 處理
# ---------------------------------------------------------------------------
async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    room: Room | None = None
    seat_idx: int | None = None

    async def send(payload):
        await ws.send_json(payload)

    async def err(msg):
        await send({"t": "error", "msg": msg})

    try:
        async for raw in ws:
            if raw.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(raw.data)
            except Exception:
                continue
            t = m.get("t")
            if room:
                room.touch()          # 有動作就更新活躍時間（給房間清理判斷）

            # ---- 大廳：開房 ----
            if t == "create":
                name = (m.get("name") or "玩家").strip()[:12]
                code = new_code()
                room = Room(code)
                rooms[code] = room
                token = secrets.token_hex(8)
                seat = Seat(name, token)
                seat.ws = ws
                seat.connected = True
                room.seats[0] = seat
                room.host_seat = 0
                seat_idx = 0
                await send({"t": "joined", "code": code, "seat": 0, "token": token})
                await room.broadcast_lobby()

            # ---- 大廳：加入 ----
            elif t == "join":
                code = (m.get("code") or "").strip().upper()
                name = (m.get("name") or "玩家").strip()[:12]
                r = rooms.get(code)
                if not r:
                    await err("找不到這個房間")
                    continue
                if r.game is not None:
                    await err("牌局已開始，無法加入")
                    continue
                free = r.find_free_seat()
                if free is None:
                    await err("房間已滿（4 人）")
                    continue
                token = secrets.token_hex(8)
                seat = Seat(name, token)
                seat.ws = ws
                seat.connected = True
                r.seats[free] = seat
                room = r
                seat_idx = free
                await send({"t": "joined", "code": code, "seat": free, "token": token})
                await room.broadcast_lobby()

            # ---- 重新連線 ----
            elif t == "reconnect":
                code = (m.get("code") or "").strip().upper()
                token = m.get("token") or ""
                r = rooms.get(code)
                if not r:
                    # 伺服器重啟／房間已回收 → 請前端清掉舊紀錄回大廳
                    await send({"t": "reconnect_failed",
                                "msg": "先前的房間已結束，請重新開房或加入"})
                    continue
                idx = r.seat_of_token(token)
                if idx is None:
                    await send({"t": "reconnect_failed",
                                "msg": "座位已不存在，請重新加入"})
                    continue
                room = r
                seat_idx = idx
                r.seats[idx].ws = ws
                r.seats[idx].connected = True
                await send({"t": "joined", "code": code, "seat": idx, "token": token})
                await room.broadcast_lobby()
                if room.game:
                    await room.broadcast_state()

            # ---- 房主設定底/台/骰規 ----
            elif t == "set_config":
                if not room or seat_idx != room.host_seat:
                    await err("只有房主可以修改設定")
                    continue
                if room.game is not None:
                    await err("牌局進行中無法改設定")
                    continue
                try:
                    b = int(m.get("base", room.base))
                    tv = int(m.get("tai_value", room.tai_value))
                    room.base = max(0, min(b, 100000))
                    room.tai_value = max(0, min(tv, 100000))
                except (TypeError, ValueError):
                    pass
                room.dice_rule = bool(m.get("dice_rule", room.dice_rule))
                try:
                    rt = int(m.get("rounds_target", room.rounds_target))
                    if rt in (1, 2, 4):
                        room.rounds_target = rt
                except (TypeError, ValueError):
                    pass
                await room.broadcast_lobby()

            # ---- 房主開局 ----
            elif t == "start":
                if not room or seat_idx != room.host_seat:
                    await err("只有房主可以開局")
                    continue
                if room.occupied() < 4:
                    await err("要 4 個人才能開局")
                    continue
                # 擲骰決定莊家（從房主位置起算）
                for s in room.seats:
                    if s:
                        s.score = 0
                room.hand_no = 0
                sd = room.roll_for_dealer(from_seat=room.host_seat)
                dealer_name = room.seats[sd["dealer"]].name if room.seats[sd["dealer"]] else ""
                await room._send_all({
                    "t": "dealer_roll",
                    "dice": sd["values"], "total": sd["total"],
                    "dealer": sd["dealer"], "dealer_name": dealer_name,
                    "msg": f"🎲 {'·'.join(map(str, sd['values']))} = {sd['total']} → {dealer_name} 做莊",
                })
                await asyncio.sleep(1.6)      # 讓大家看清楚骰子結果
                room.start_new_hand()
                await room.broadcast_state()

            # ---- 離開房間（退出牌局，回大廳）----
            elif t == "leave":
                if not room or seat_idx is None:
                    await send({"t": "left"})
                    continue
                r, idx = room, seat_idx
                r.seats[idx] = None
                # 牌局進行中有人退出 → 中止本局，其他人回等待室（分數保留）
                if r.game is not None:
                    r.abandon_game()
                    await r._send_all({"t": "notice",
                                       "msg": "有玩家離開，本局中止，回到等待室"})
                r.reassign_host()
                r.touch()
                await send({"t": "left"})        # 通知自己已離開
                room, seat_idx = None, None
                if r.occupied() == 0:
                    rooms.pop(r.code, None)      # 沒人了就收掉房間
                else:
                    await r.broadcast_lobby()

            # ---- 房主重開牌局（重新洗牌發牌，分數保留）----
            elif t == "restart":
                if not room or seat_idx != room.host_seat:
                    await err("只有房主可以重開牌局")
                    continue
                if room.occupied() < 4:
                    await err("要 4 個人才能開局")
                    continue
                room.abandon_game()
                if room.finished:
                    # 整場已打完 → 重開新的一場：分數歸零、重新擲骰決定莊家
                    for s in room.seats:
                        if s:
                            s.score = 0
                    room.hand_no = 0
                    sd = room.roll_for_dealer(from_seat=room.host_seat)
                    nm = room.seats[sd["dealer"]].name if room.seats[sd["dealer"]] else ""
                    await room._send_all({
                        "t": "dealer_roll", "dice": sd["values"], "total": sd["total"],
                        "dealer": sd["dealer"], "dealer_name": nm,
                        "msg": f"🎲 {'·'.join(map(str, sd['values']))} = {sd['total']} → {nm} 做莊"})
                    await asyncio.sleep(1.6)
                else:
                    await room._send_all({"t": "notice", "msg": "房主重開了牌局"})
                room.start_new_hand()
                await room.broadcast_state()

            # ---- 下一局 ----
            elif t == "next":
                if not room or seat_idx != room.host_seat:
                    await err("只有房主可以開下一局")
                    continue
                if room.finished:
                    await err("整場已結束，請按「重開牌局」開始新的一場")
                    continue
                if room.game and room.game.phase == "over":
                    room.start_new_hand()
                    await room.broadcast_state()

            # ---- 牌局動作 ----
            elif t in ("discard", "claim", "self") and room and room.game:
                g = room.game
                changed = False
                if t == "discard":
                    changed = g.discard(seat_idx, m.get("tile"))
                elif t == "claim":
                    changed = g.claim(seat_idx, m.get("action"), m.get("tiles"))
                elif t == "self":
                    a = m.get("action")
                    if a == "tsumo":
                        changed = g.declare_tsumo(seat_idx)
                    elif a == "ankong":
                        changed = g.declare_ankong(seat_idx, m.get("tile"))
                    elif a == "addkong":
                        changed = g.declare_addkong(seat_idx, m.get("tile"))
                if not changed:
                    await err("這個動作現在不能執行")
                    continue
                if g.phase == "over":
                    room.settle()
                await room.broadcast_state()
                if g.phase == "over":
                    await room.broadcast_lobby()

    finally:
        if room and seat_idx is not None and room.seats[seat_idx]:
            room.seats[seat_idx].connected = False
            room.seats[seat_idx].ws = None
            try:
                await room.broadcast_lobby()
            except Exception:
                pass
    return ws


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"))


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    # 避免瀏覽器拿到舊的前端檔（更新後朋友都能拿到最新版）
    if request.path == "/" or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


async def healthz(request):
    """給雲端主機做健康檢查用。"""
    return web.json_response({
        "ok": True,
        "rooms": len(rooms),
        "players": sum(r.occupied() for r in rooms.values()),
    })


# 房間清理：常駐伺服器若不清，rooms 會無限成長
ROOM_TTL_EMPTY = 10 * 60        # 沒人連線的房間保留 10 分鐘（讓人有機會重連）
ROOM_TTL_IDLE = 6 * 60 * 60     # 完全沒動靜的房間 6 小時後回收


async def cleanup_rooms(app):
    try:
        while True:
            await asyncio.sleep(120)
            now = time.time()
            for code in [c for c, r in rooms.items()
                         if (not r.anyone_connected() and now - r.last_active > ROOM_TTL_EMPTY)
                         or now - r.last_active > ROOM_TTL_IDLE]:
                rooms.pop(code, None)
    except asyncio.CancelledError:
        pass


async def _on_start(app):
    app["cleanup"] = asyncio.create_task(cleanup_rooms(app))


async def _on_cleanup(app):
    task = app.get("cleanup")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def make_app() -> web.Application:
    app = web.Application(middlewares=[no_cache])
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.on_startup.append(_on_start)
    app.on_cleanup.append(_on_cleanup)
    return app


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    port = int(os.environ.get("PORT", "8080"))
    print(f"麻將伺服器啟動：http://localhost:{port}")
    web.run_app(make_app(), host="0.0.0.0", port=port)
