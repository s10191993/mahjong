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
import poker as pk
from poker_game import PokerTable, STREETS as POKER_STREETS

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

DEFAULT_BASE = 100      # 預設底
DEFAULT_TAI = 20        # 預設每台
DEFAULT_SB = 10         # 德州：預設小盲
DEFAULT_BB = 20         # 德州：預設大盲
DEFAULT_STACK = 1000    # 德州：預設起始籌碼
DEFAULT_TURN_SECONDS = 20   # 每個行動的倒數秒數（0 = 關閉）
AFK_TURN_SECONDS = 3        # 已判定暫離者的倒數（縮短，別讓整桌等）
AFK_AFTER = 2               # 連續逾時幾次就算暫離
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
        self.afk_count = 0      # 連續逾時次數
        self.afk = False        # 暫離：倒數縮短，不讓整桌一直等
        self.voice = False      # 是否已開語音（給其他人知道要不要跟他連線）


class Room:
    def __init__(self, code: str, game_type: str = "mahjong"):
        self.code = code
        self.game_type = game_type if game_type in ("mahjong", "poker") else "mahjong"
        self.max_seats = 8 if self.game_type == "poker" else 4
        self.min_players = 2 if self.game_type == "poker" else 4
        self.seats: list[Seat | None] = [None] * self.max_seats
        self.host_seat = 0
        self.game: Game | None = None
        # 德州撲克
        self.table: PokerTable | None = None
        self.small_blind = DEFAULT_SB
        self.big_blind = DEFAULT_BB
        self.start_stack = DEFAULT_STACK
        self.bounty_27 = True        # 2-7 收池／秀牌，每家付 2.5 大盲
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
        # ---- 行動倒數（避免有人離開整桌卡死）----
        self.turn_seconds = DEFAULT_TURN_SECONDS   # 0 = 關閉倒數
        self.deadline: float | None = None         # 這個行動的截止時間
        self.deadline_key: str | None = None       # 用來判斷「還是不是同一個等待狀態」

    def touch(self):
        self.last_active = time.time()

    # ---- 行動倒數 ------------------------------------------------------------
    def waiting_key(self) -> tuple[str, list[int]] | None:
        """
        目前在等誰行動。回傳 (狀態指紋, 等待中的座位清單)；沒在等人則 None。
        指紋只要局面一變就會不同，用來判斷倒數該不該重新計時。
        """
        if self.game_type == "poker":
            t = self.table
            if not t or t.phase not in POKER_STREETS or t.to_act is None:
                return None
            return (f"p{t.hand_no}:{t.phase}:{t.to_act}:{t.pot}:{t.current_bet}",
                    [t.to_act])
        g = self.game
        if not g:
            return None
        if g.phase == "await_discard":
            melds = sum(len(p.melds) for p in g.players)
            return (f"d{self.hand_no}:{g.turn}:{g.discard_count}:{len(g.wall)}:{melds}",
                    [g.turn])
        if g.phase == "await_reaction":
            waiting = [s for s in g.pending if s not in g.responses]
            if not waiting:
                return None
            return (f"r{self.hand_no}:{g.discard_count}", waiting)
        return None

    def refresh_deadline(self):
        """局面變了就重新計時；沒在等人就清掉倒數。"""
        wk = self.waiting_key()
        if not wk or not self.turn_seconds:
            self.deadline = self.deadline_key = None
            return
        key, seats = wk
        if key != self.deadline_key:
            self.deadline_key = key
            # 只要有一位是暫離狀態，就用短倒數
            afk = any(self.seats[s] and self.seats[s].afk for s in seats
                      if 0 <= s < len(self.seats))
            secs = AFK_TURN_SECONDS if afk else self.turn_seconds
            self.deadline = time.time() + secs

    def deadline_ms(self) -> int | None:
        if self.deadline is None:
            return None
        return max(0, int((self.deadline - time.time()) * 1000))

    def voice_peers(self) -> list[int]:
        """目前有開語音而且還連著的座位。"""
        return [i for i, s in enumerate(self.seats)
                if s and s.connected and s.voice]

    def clear_afk(self, seat: int):
        """玩家自己動了 → 不再算暫離。"""
        s = self.seats[seat] if 0 <= seat < len(self.seats) else None
        if s and (s.afk or s.afk_count):
            s.afk = False
            s.afk_count = 0

    def _mark_timeout(self, seat: int) -> bool:
        """記一次逾時，回傳是否「剛好變成暫離」。"""
        s = self.seats[seat] if 0 <= seat < len(self.seats) else None
        if not s:
            return False
        s.afk_count += 1
        if not s.afk and s.afk_count >= AFK_AFTER:
            s.afk = True
            return True
        return False

    def apply_timeout(self) -> list[str]:
        """時間到 → 幫他做最安全的動作。回傳要廣播的訊息。"""
        msgs: list[str] = []
        wk = self.waiting_key()
        if not wk:
            return msgs
        _, seats = wk

        def name_of(i):
            return self.seats[i].name if 0 <= i < len(self.seats) and self.seats[i] else "玩家"

        if self.game_type == "poker":
            t, seat = self.table, seats[0]
            acts = t.legal_actions(seat)
            if "check" in acts:
                t.act(seat, "check")
                msgs.append(f"⏱ {name_of(seat)} 逾時，自動過牌")
            else:
                t.act(seat, "fold")
                msgs.append(f"⏱ {name_of(seat)} 逾時，自動蓋牌")
            if self._mark_timeout(seat):
                msgs.append(f"{name_of(seat)} 連續逾時，設為暫離")
            return msgs

        g = self.game
        if g.phase == "await_discard":
            seat = seats[0]
            p = g.players[seat]
            # 打掉剛摸的那張最安全（等同「摸什麼打什麼」）
            tile = g.last_draw if (g.last_draw and g.last_draw in p.hand) else \
                (p.hand[-1] if p.hand else None)
            if tile:
                g.discard(seat, tile)
                msgs.append(f"⏱ {name_of(seat)} 逾時，自動打出 {mj.name_of(tile)}")
            if self._mark_timeout(seat):
                msgs.append(f"{name_of(seat)} 連續逾時，設為暫離")
        elif g.phase == "await_reaction":
            for s in list(seats):
                if g.phase != "await_reaction" or s in g.responses:
                    continue          # 中途被別人的胡/碰結算掉了
                g.claim(s, "pass")
                if self._mark_timeout(s):
                    msgs.append(f"{name_of(s)} 連續逾時，設為暫離")
            msgs.append("⏱ 逾時，未回應者自動過")
        return msgs

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
        self.table = None
        self.dice = None
        self.dice_bonus = 0
        self.dice_double = False
        self.dice_patterns = []

    def occupied(self) -> int:
        return sum(1 for s in self.seats if s is not None)

    def find_free_seat(self) -> int | None:
        for i, s in enumerate(self.seats):
            if s is not None:
                continue
            # 德州：這手還在用的座位（有投入或離開者尚未清掉）不能給新人坐，
            # 否則會覆蓋掉投入金額，彩池就算錯了
            if self.game_type == "poker" and self.table and self.table.seat_busy(i):
                continue
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
            "game_type": self.game_type,
            "max_seats": self.max_seats,
            "min_players": self.min_players,
            "host_seat": self.host_seat,
            "started": (self.table is not None) if self.game_type == "poker"
                       else (self.game is not None),
            "config": {"base": self.base, "tai_value": self.tai_value,
                       "dice_rule": self.dice_rule, "rounds_target": self.rounds_target,
                       "small_blind": self.small_blind, "big_blind": self.big_blind,
                       "start_stack": self.start_stack, "bounty_27": self.bounty_27,
                       "turn_seconds": self.turn_seconds},
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
        payload["voice_peers"] = self.voice_peers()
        await self._send_all(payload)

    async def broadcast_state(self):
        """牌局進行中：每位玩家送公開狀態 + 自己的私有狀態。"""
        self.refresh_deadline()
        if self.game_type == "poker":
            return await self._broadcast_poker()
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
        pub["deadline_ms"] = self.deadline_ms()
        pub["turn_seconds"] = self.turn_seconds
        pub["afk"] = [bool(s and s.afk) for s in self.seats]
        pub["connected"] = [bool(s and s.connected) for s in self.seats]
        if self.finished:
            pub["standings"] = self.standings()
        for i, seat in enumerate(self.seats):
            if seat and seat.connected and seat.ws is not None:
                msg = {"t": "state", "public": pub, "private": self.game.private_state(i),
                       "hand_no": self.hand_no}
                await self._safe_send(seat.ws, msg)

    async def _broadcast_poker(self):
        """德州：公開狀態給所有人，底牌只給本人。"""
        if not self.table:
            return
        pub = self.table.public_state()
        pub["config"] = {"small_blind": self.small_blind, "big_blind": self.big_blind,
                         "start_stack": self.start_stack, "bounty_27": self.bounty_27}
        pub["game_type"] = "poker"
        pub["settlement"] = self.table.settlement(self.start_stack)
        pub["deadline_ms"] = self.deadline_ms()
        pub["turn_seconds"] = self.turn_seconds
        pub["afk"] = [bool(s and s.afk) for s in self.seats]
        pub["connected"] = [bool(s and s.connected) for s in self.seats]
        for i, seat in enumerate(self.seats):
            if seat and seat.connected and seat.ws is not None:
                msg = {"t": "state", "game_type": "poker", "public": pub,
                       "private": self.table.private_state(i),
                       "hand_no": self.table.hand_no}
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
                room = Room(code, game_type=m.get("game_type") or "mahjong")
                rooms[code] = room
                token = secrets.token_hex(8)
                seat = Seat(name, token)
                seat.ws = ws
                seat.connected = True
                room.seats[0] = seat
                room.host_seat = 0
                seat_idx = 0
                await send({"t": "joined", "code": code, "seat": 0, "token": token,
                            "game_type": room.game_type})
                await room.broadcast_lobby()

            # ---- 大廳：加入 ----
            elif t == "join":
                code = (m.get("code") or "").strip().upper()
                name = (m.get("name") or "玩家").strip()[:12]
                r = rooms.get(code)
                if not r:
                    await err("找不到這個房間")
                    continue
                # 麻將固定 4 人，開局後不能加入；德州是現金桌，隨時可入座
                if r.game_type != "poker" and r.game is not None:
                    await err("牌局已開始，無法加入")
                    continue
                free = r.find_free_seat()
                if free is None:
                    await err(f"房間已滿（{r.max_seats} 人）")
                    continue
                token = secrets.token_hex(8)
                seat = Seat(name, token)
                seat.ws = ws
                seat.connected = True
                r.seats[free] = seat
                room = r
                seat_idx = free
                # 德州牌局進行中入座：這手先旁觀，下一手才發牌
                mid_game = (r.game_type == "poker" and r.table is not None)
                if mid_game:
                    r.table.join_mid_game(free, name, r.start_stack)
                await send({"t": "joined", "code": code, "seat": free, "token": token,
                            "game_type": r.game_type})
                await room.broadcast_lobby()
                if mid_game:
                    await r._send_all({"t": "notice",
                                       "msg": f"{name} 入座，下一手開始"})
                    await room.broadcast_state()   # 直接把他帶進牌桌畫面

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
                await send({"t": "joined", "code": code, "seat": idx, "token": token,
                            "game_type": r.game_type})
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
                # 德州：大小盲與起始籌碼
                try:
                    sb = int(m.get("small_blind", room.small_blind))
                    bb = int(m.get("big_blind", room.big_blind))
                    stk = int(m.get("start_stack", room.start_stack))
                    room.small_blind = max(1, min(sb, 100000))
                    room.big_blind = max(room.small_blind, min(bb, 200000))
                    room.start_stack = max(room.big_blind * 2, min(stk, 10000000))
                except (TypeError, ValueError):
                    pass
                if "bounty_27" in m:
                    room.bounty_27 = bool(m.get("bounty_27"))
                try:
                    ts = int(m.get("turn_seconds", room.turn_seconds))
                    room.turn_seconds = 0 if ts <= 0 else max(5, min(ts, 120))
                except (TypeError, ValueError):
                    pass
                await room.broadcast_lobby()

            # ---- 房主開局 ----
            elif t == "start":
                if not room or seat_idx != room.host_seat:
                    await err("只有房主可以開局")
                    continue
                if room.occupied() < room.min_players:
                    await err(f"要 {room.min_players} 個人才能開局")
                    continue
                if room.game_type == "poker":
                    room.table = PokerTable(room.small_blind, room.big_blind,
                                            room.start_stack,
                                            bounty_27=room.bounty_27)
                    for i, s in enumerate(room.seats):
                        if s:
                            room.table.seat_player(i, s.name)
                    room.table.start_hand(bomb_pot=bool(m.get("bomb_pot")))
                    if room.table.is_bomb:
                        await room._send_all({"t": "notice",
                            "msg": f"💣 炸彈彩池！每家底注 {room.table.big_blind*room.table.BOMB_ANTE_BB}，直接翻牌"})
                    await room.broadcast_state()
                    await room.broadcast_lobby()
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
                # 德州：牌局不中止，離開者蓋牌讓局繼續（這手結束才真正移除）
                if r.game_type == "poker" and r.table is not None:
                    nm = r.table.players.get(idx).name if idx in r.table.players else ""
                    r.table.mark_left(idx)
                    await r._send_all({"t": "notice", "msg": f"{nm} 離開了牌桌"})
                    if r.occupied() > 0:
                        await r.broadcast_state()
                # 麻將：進行中有人退出 → 中止本局，其他人回等待室（分數保留）
                elif r.game is not None:
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
                if room.occupied() < room.min_players:
                    await err(f"要 {room.min_players} 個人才能開局")
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
                if room.game_type == "poker":
                    if not room.table:
                        await err("還沒開始")
                        continue
                    if len(room.table.active_seats()) < 2:
                        await err("剩下的人不足 2 位，請重開牌局")
                        continue
                    room.table.start_hand(bomb_pot=bool(m.get("bomb_pot")))
                    if room.table.is_bomb:
                        await room._send_all({"t": "notice",
                            "msg": f"💣 炸彈彩池！每家底注 {room.table.big_blind*room.table.BOMB_ANTE_BB}，直接翻牌"})
                    await room.broadcast_state()
                    continue
                if room.finished:
                    await err("整場已結束，請按「重開牌局」開始新的一場")
                    continue
                if room.game and room.game.phase == "over":
                    room.start_new_hand()
                    await room.broadcast_state()

            # ---- 語音：宣告自己開/關語音 ----
            elif t == "voice_state" and room and seat_idx is not None:
                st = room.seats[seat_idx]
                if st:
                    st.voice = bool(m.get("on"))
                await room._send_all({"t": "voice_peers",
                                      "peers": room.voice_peers()})

            # ---- 語音：WebRTC 信令轉發（offer / answer / ice）----
            # 音訊本身走點對點，伺服器只幫忙牽線，不碰任何語音資料。
            elif t == "rtc" and room and seat_idx is not None:
                try:
                    to = int(m.get("to"))
                except (TypeError, ValueError):
                    continue
                if not (0 <= to < len(room.seats)):
                    continue
                target = room.seats[to]
                if not target or not target.connected or target.ws is None:
                    continue
                await room._safe_send(target.ws, {
                    "t": "rtc",
                    "from": seat_idx,          # 由伺服器填，不信任前端
                    "kind": m.get("kind"),
                    "data": m.get("data"),
                })

            # ---- 德州：秀牌（沒攤牌就收池的贏家可選擇亮牌，2-7 才領得到獎金）----
            elif t == "poker_show" and room and room.table:
                if not room.table.show_cards(seat_idx):
                    await err("現在不能秀牌")
                    continue
                nm = room.seats[seat_idx].name if room.seats[seat_idx] else ""
                b = (room.table.result or {}).get("bounty27")
                msg = f"{nm} 秀牌"
                if b:
                    msg = f"🎉 {nm} 用 2-7 收池！每家付 {b['each']}，共收 {b['total']}"
                await room._send_all({"t": "notice", "msg": msg})
                await room.broadcast_state()

            # ---- 德州：補碼 ----
            elif t == "rebuy" and room and room.table:
                amt = m.get("amount")
                try:
                    amt = int(amt)
                except (TypeError, ValueError):
                    amt = 0
                if not room.table.rebuy(seat_idx, amt):
                    await err("現在不能補碼（籌碼未低於 300、或牌局進行中）")
                    continue
                nm = room.seats[seat_idx].name if room.seats[seat_idx] else ""
                await room._send_all({"t": "notice", "msg": f"{nm} 補碼 {amt}"})
                await room.broadcast_state()

            # ---- 德州：下注動作 ----
            elif t == "poker_act" and room and room.table:
                room.clear_afk(seat_idx)
                ok = room.table.act(seat_idx, m.get("action"), m.get("amount"))
                if not ok:
                    await err("這個動作現在不能執行")
                    continue
                await room.broadcast_state()
                if room.table.phase == "over":
                    # 把籌碼同步回座位分數，方便大廳顯示
                    for i, s in enumerate(room.seats):
                        if s and i in room.table.players:
                            pp = room.table.players[i]
                            # 淨輸贏＝目前籌碼 −（起始籌碼＋補碼總額）
                            s.score = pp.stack - room.start_stack - pp.rebuy_total
                    await room.broadcast_lobby()

            # ---- 牌局動作 ----
            elif t in ("discard", "claim", "self") and room and room.game:
                room.clear_afk(seat_idx)
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
            room.seats[seat_idx].voice = False      # 斷線就離開語音
            try:
                await room.broadcast_lobby()
                await room._send_all({"t": "voice_peers",
                                      "peers": room.voice_peers()})
            except Exception:
                pass
    return ws


async def index(request):
    return web.FileResponse(os.path.join(STATIC, "index.html"))


IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".gif")


@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    path = request.path
    if path.startswith("/static/") and path.lower().endswith(IMG_EXTS):
        # 牌面圖／圖示：一定要讓瀏覽器快取。
        # 牌桌每次重繪都會重建幾十個 <img>，不快取的話每次出牌都重新下載，
        # 打久了就會愈來愈卡。
        resp.headers["Cache-Control"] = "public, max-age=604800"
    elif path == "/" or path.startswith("/static/"):
        # HTML / JS / CSS 不快取，更新後朋友一定拿到最新版
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


async def turn_watchdog(app):
    """每 0.5 秒巡一次：有人行動逾時就幫他出手，避免整桌卡死。"""
    try:
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            for room in list(rooms.values()):
                try:
                    if room.deadline is None or now < room.deadline:
                        continue
                    msgs = room.apply_timeout()
                    room.refresh_deadline()
                    for m in msgs:
                        await room._send_all({"t": "notice", "msg": m})
                    # 結算（麻將胡牌／德州本手結束）
                    if room.game_type == "poker":
                        if room.table and room.table.phase == "over":
                            for i, s in enumerate(room.seats):
                                if s and i in room.table.players:
                                    pp = room.table.players[i]
                                    s.score = pp.stack - room.start_stack - pp.rebuy_total
                    elif room.game and room.game.phase == "over":
                        room.settle()
                    await room.broadcast_state()
                    if ((room.game_type == "poker" and room.table
                         and room.table.phase == "over")
                            or (room.game and room.game.phase == "over")):
                        await room.broadcast_lobby()
                except Exception:
                    # 單一房間出錯不能影響其他房間
                    room.deadline = None
    except asyncio.CancelledError:
        pass


async def _on_start(app):
    app["cleanup"] = asyncio.create_task(cleanup_rooms(app))
    app["watchdog"] = asyncio.create_task(turn_watchdog(app))


async def _on_cleanup(app):
    for key in ("cleanup", "watchdog"):
        task = app.get(key)
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
