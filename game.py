# -*- coding: utf-8 -*-
"""
台灣麻將 16 張 —— 單局狀態機（伺服器權威）

一個 Game 物件代表「一局」牌。座位 0~3，座位 seat 的下家是 (seat+1)%4。
Game 不做任何網路 I/O；伺服器負責把 public_state()/private_state() 送給前端，
並把玩家動作轉成 discard()/claim()/self_action() 呼叫。

回合流程：
  發牌16 → 補花 → 莊家摸1 → [await_discard]
  打牌 → [await_reaction] 其他家可 胡/碰/槓/吃/過（有優先權）
  無人反應或全過 → 下家摸牌 → [await_discard] ...
  摸到牌可 自摸胡 / 暗槓 / 加槓
  牌牆摸完 → 流局
"""
from __future__ import annotations
import random
from typing import Optional

import mahjong as mj

SEAT_WINDS = ("we", "ws", "ww", "wn")   # 座位對應的門風：0東 1南 2西 3北
HAND_SIZE = 16


class Meld:
    """一組亮出的面子。kind: 'pong'|'chow'|'kong'|'ankong'（暗槓）|'addkong'（加槓）"""

    def __init__(self, kind: str, tiles: list[str], from_seat: Optional[int] = None,
                 claimed: Optional[str] = None):
        self.kind = kind
        self.tiles = tiles
        self.from_seat = from_seat   # 這張是從哪一家來的（暗槓為 None）
        self.claimed = claimed       # 吃/碰/槓 進來的那一張（給前端擺位用）

    def to_dict(self):
        return {"kind": self.kind, "tiles": self.tiles,
                "from_seat": self.from_seat, "claimed": self.claimed}


class Player:
    def __init__(self, seat: int):
        self.seat = seat
        self.hand: list[str] = []
        self.melds: list[Meld] = []
        self.flowers: list[str] = []
        self.discards: list[str] = []

    @property
    def exposed_meld_count(self) -> int:
        return len(self.melds)

    def concealed_for_win(self) -> list[str]:
        return self.hand

    def is_menqing(self) -> bool:
        """門清：沒有吃碰明槓（暗槓仍算門清）。"""
        return all(m.kind == "ankong" for m in self.melds)


class Game:
    def __init__(self, dealer: int = 0, seed: Optional[int] = None,
                 round_wind: str = "we", dealer_streak: int = 0):
        self.rng = random.Random(seed)
        self.players = [Player(i) for i in range(4)]
        self.dealer = dealer
        self.round_wind = round_wind
        self.dealer_streak = dealer_streak      # 連莊數（拉莊台用）
        self.wall: list[str] = []
        self.turn = dealer
        self.phase = "init"                     # init|await_discard|await_reaction|over
        self.last_discard: Optional[tuple[int, str]] = None
        self.pending: dict[int, list[str]] = {}   # seat -> 可選動作清單
        self.responses: dict[int, dict] = {}      # seat -> {'action':..., ...}
        self.result: Optional[dict] = None
        self.last_draw: Optional[str] = None      # 本回合剛摸到的牌（判斷槓上開花/自摸）
        self.log: list[str] = []
        # ---- 計分用狀態旗標 ----
        self.after_kong = False       # 剛槓完補牌 → 自摸即槓上開花
        self.is_last_draw = False     # 剛摸的是牌牆最後一張 → 自摸即海底
        self.discard_count = 0        # 全場已打出的牌數（判斷天/地/人胡）
        self.any_claim = False        # 是否發生過吃碰槓（破天地胡的第一巡）
        self.hedi_discard = False     # 這張棄牌是牌牆摸完後打的 → 胡即河底
        self.robbing: Optional[dict] = None   # 搶槓進行中 {'tile','owner'}
        self.qianggang = False        # 本次胡為搶槓

    # ---- 牌牆 ----------------------------------------------------------------
    def _draw_front(self) -> Optional[str]:
        return self.wall.pop(0) if self.wall else None

    def _draw_tail(self) -> Optional[str]:
        return self.wall.pop() if self.wall else None

    def _replace_flowers(self, seat: int):
        """補花：把手上的花移到花區，從牌尾補一張，直到手上無花。"""
        p = self.players[seat]
        while True:
            flowers = [t for t in p.hand if mj.is_flower(t)]
            if not flowers:
                break
            for f in flowers:
                p.hand.remove(f)
                p.flowers.append(f)
                repl = self._draw_tail()
                if repl is None:
                    return
                p.hand.append(repl)

    # ---- 開局 ----------------------------------------------------------------
    def start(self):
        self.wall = mj.build_wall()
        self.rng.shuffle(self.wall)
        # 發 16 張給每家
        for _ in range(HAND_SIZE):
            for s in range(4):
                self.players[s].hand.append(self._draw_front())
        # 補花（依莊家順序）
        for s in range(4):
            self._replace_flowers(self.dealer_order(s))
        for p in self.players:
            p.hand = mj.sort_hand(p.hand)
        # 莊家摸第一張
        self.turn = self.dealer
        self._draw_for_turn()

    def dealer_order(self, offset: int) -> int:
        return (self.dealer + offset) % 4

    # ---- 摸牌 ----------------------------------------------------------------
    def _draw_for_turn(self):
        """輪到 self.turn 的玩家摸牌並進入 await_discard；牌牆空則流局。"""
        p = self.players[self.turn]
        tile = self._draw_front()
        if tile is None:
            return self._draw_game()
        # 摸到花要補
        if mj.is_flower(tile):
            p.flowers.append(tile)
            while True:
                repl = self._draw_tail()
                if repl is None:
                    return self._draw_game()
                if mj.is_flower(repl):
                    p.flowers.append(repl)
                    continue
                tile = repl
                break
        p.hand.append(tile)
        p.hand = mj.sort_hand(p.hand)
        self.last_draw = tile
        self.after_kong = False
        self.is_last_draw = (len(self.wall) == 0)
        self.phase = "await_discard"
        self.pending = {}
        self.responses = {}

    # ---- 玩家在自己回合可做的事 ---------------------------------------------
    def self_options(self, seat: int) -> dict:
        """回傳輪到 seat 時可執行的特殊動作（自摸、暗槓、加槓）。"""
        if self.phase != "await_discard" or self.turn != seat:
            return {}
        p = self.players[seat]
        opts: dict = {}
        if mj.can_win(p.hand, p.exposed_meld_count):
            opts["tsumo"] = True                       # 自摸（含哩咕哩咕/十六不搭）
        ankong = mj.concealed_kong_options(p.hand)     # 暗槓
        if ankong:
            opts["ankong"] = ankong
        # 加槓：手上有一張與已碰的牌相同
        addable = [m.tiles[0] for m in p.melds
                   if m.kind == "pong" and m.tiles[0] in p.hand]
        if addable:
            opts["addkong"] = addable
        return opts

    def discard(self, seat: int, tile: str) -> bool:
        if self.phase != "await_discard" or self.turn != seat:
            return False
        p = self.players[seat]
        if tile not in p.hand:
            return False
        p.hand.remove(tile)
        p.hand = mj.sort_hand(p.hand)
        p.discards.append(tile)
        self.last_discard = (seat, tile)
        self.last_draw = None
        self.after_kong = False
        self.discard_count += 1
        self.hedi_discard = (len(self.wall) == 0)   # 牌牆已空 → 這張可被河底胡
        self._open_reactions(seat, tile)
        return True

    def declare_ankong(self, seat: int, tile: str) -> bool:
        p = self.players[seat]
        if self.phase != "await_discard" or self.turn != seat:
            return False
        if p.hand.count(tile) != 4:
            return False
        for _ in range(4):
            p.hand.remove(tile)
        p.melds.append(Meld("ankong", [tile] * 4))
        self.any_claim = True
        # 槓後補一張再打
        self._draw_for_turn_after_kong(seat)
        return True

    def declare_addkong(self, seat: int, tile: str) -> bool:
        p = self.players[seat]
        if self.phase != "await_discard" or self.turn != seat:
            return False
        pong = next((m for m in p.melds if m.kind == "pong" and m.tiles[0] == tile), None)
        if not pong or tile not in p.hand:
            return False
        # 搶槓：其他家若正聽這張，可在此胡牌
        robbers = {}
        for offset in range(1, 4):
            s = (seat + offset) % 4
            other = self.players[s]
            if mj.can_win(other.hand + [tile], other.exposed_meld_count):
                robbers[s] = ["hu"]
        if robbers:
            self.robbing = {"tile": tile, "owner": seat}
            self.pending = robbers
            self.responses = {}
            self.phase = "await_reaction"
            self.last_discard = (seat, tile)   # 供搶槓計分（放槍者=加槓者）
            return True
        # 無人搶槓 → 完成加槓並補牌
        p.hand.remove(tile)
        pong.kind = "addkong"
        pong.tiles = [tile] * 4
        self.any_claim = True
        self._draw_for_turn_after_kong(seat)
        return True

    def _finish_addkong(self, owner: int, tile: str):
        """搶槓沒人胡 → 真正完成加槓。"""
        p = self.players[owner]
        pong = next((m for m in p.melds if m.kind == "pong" and m.tiles[0] == tile), None)
        if pong and tile in p.hand:
            p.hand.remove(tile)
            pong.kind = "addkong"
            pong.tiles = [tile] * 4
        self.any_claim = True
        self.robbing = None
        self._draw_for_turn_after_kong(owner)

    def _draw_for_turn_after_kong(self, seat: int):
        """槓後從牌尾補一張（嶺上），可槓上開花。"""
        repl = self._draw_tail()
        if repl is None:
            return self._draw_game()
        p = self.players[seat]
        while mj.is_flower(repl):
            p.flowers.append(repl)
            repl = self._draw_tail()
            if repl is None:
                return self._draw_game()
        p.hand.append(repl)
        p.hand = mj.sort_hand(p.hand)
        self.last_draw = repl
        self.after_kong = True                 # 槓上這張 → 自摸即槓上開花
        self.is_last_draw = (len(self.wall) == 0)
        self.phase = "await_discard"

    # ---- 別人打牌後的反應階段 -----------------------------------------------
    def _open_reactions(self, discarder: int, tile: str):
        self.pending = {}
        for offset in range(1, 4):
            s = (discarder + offset) % 4
            p = self.players[s]
            acts = []
            # 胡（食胡，含哩咕哩咕/十六不搭）
            if mj.can_win(p.hand + [tile], p.exposed_meld_count):
                acts.append("hu")
            # 槓（明槓）
            if mj.can_kong_from_discard(p.hand, tile):
                acts.append("kong")
            # 碰
            if mj.can_pong(p.hand, tile):
                acts.append("pong")
            # 吃（只有下家）
            if offset == 1 and mj.chow_options(p.hand, tile):
                acts.append("chow")
            if acts:
                self.pending[s] = acts
        if not self.pending:
            self._advance_turn(discarder)
        else:
            self.phase = "await_reaction"
            self.responses = {}

    def claim(self, seat: int, action: str, tiles: Optional[list[str]] = None) -> bool:
        """
        玩家對別人打出的牌做反應。action: 'hu'|'kong'|'pong'|'chow'|'pass'
        chow 需帶 tiles=[另兩張]。所有有反應權的人回覆後才結算。
        """
        if self.phase != "await_reaction" or seat not in self.pending:
            return False
        if action != "pass" and action not in self.pending[seat]:
            return False
        self.responses[seat] = {"action": action, "tiles": tiles}
        if self._ready_to_resolve():
            self._resolve_reactions()
        return True

    def _ready_to_resolve(self) -> bool:
        """
        何時可以結算：
          - 所有有反應權的人都回覆了；或
          - 已有人喊胡 → 只需再等其他「也能胡」的人回覆（一炮多響要讓大家都有機會喊）
        """
        if len(self.responses) == len(self.pending):
            return True
        if any(r["action"] == "hu" for r in self.responses.values()):
            hu_capable = [s for s, acts in self.pending.items() if "hu" in acts]
            return all(s in self.responses for s in hu_capable)
        return False

    def _resolve_reactions(self):
        resp = self.responses

        # 0) 搶槓進行中：只有胡有意義
        if self.robbing:
            owner = self.robbing["owner"]
            tile = self.robbing["tile"]
            huers = [s for s, r in resp.items() if r["action"] == "hu"]
            if huers:
                huers.sort(key=lambda s: (s - owner) % 4)
                self.qianggang = True
                return self._win(huers, tile, self_draw=False, discarder=owner)
            return self._finish_addkong(owner, tile)

        discarder, tile = self.last_discard

        # 1) 胡最優先；可多人同時胡（一炮多響），依離放槍者由近到遠排序
        huers = [s for s, r in resp.items() if r["action"] == "hu"]
        if huers:
            huers.sort(key=lambda s: (s - discarder) % 4)
            return self._win(huers, tile, self_draw=False, discarder=discarder)

        # 2) 槓 / 碰（互斥，最多一人）
        for s, r in resp.items():
            if r["action"] == "kong":
                return self._do_kong_from_discard(s, tile, discarder)
        for s, r in resp.items():
            if r["action"] == "pong":
                return self._do_pong(s, tile, discarder)

        # 3) 吃（下家）
        for s, r in resp.items():
            if r["action"] == "chow":
                return self._do_chow(s, tile, r["tiles"], discarder)

        # 全部過 → 下家摸牌
        self._advance_turn(discarder)

    def _remove_discard_tile(self, discarder: int):
        """把被吃碰槓的那張從打牌者的棄牌堆移除（已被拿走）。"""
        self.players[discarder].discards.pop()

    def _do_pong(self, seat: int, tile: str, discarder: int):
        p = self.players[seat]
        p.hand.remove(tile)
        p.hand.remove(tile)
        p.melds.append(Meld("pong", [tile] * 3, from_seat=discarder, claimed=tile))
        self._remove_discard_tile(discarder)
        self.any_claim = True
        self.turn = seat
        self.phase = "await_discard"
        self.last_draw = None
        self.pending = {}
        self.responses = {}

    def _do_kong_from_discard(self, seat: int, tile: str, discarder: int):
        p = self.players[seat]
        for _ in range(3):
            p.hand.remove(tile)
        p.melds.append(Meld("kong", [tile] * 4, from_seat=discarder, claimed=tile))
        self._remove_discard_tile(discarder)
        self.any_claim = True
        self.turn = seat
        self.pending = {}
        self.responses = {}
        self._draw_for_turn_after_kong(seat)

    def _do_chow(self, seat: int, tile: str, others: list[str], discarder: int):
        p = self.players[seat]
        if not others or any(o not in p.hand for o in others):
            # 保險：改用第一組合法組合
            opts = mj.chow_options(p.hand, tile)
            if not opts:
                return self._advance_turn(discarder)
            others = list(opts[0])
        for o in others:
            p.hand.remove(o)
        meld_tiles = mj.sort_hand([tile] + others)
        p.melds.append(Meld("chow", meld_tiles, from_seat=discarder, claimed=tile))
        self._remove_discard_tile(discarder)
        self.any_claim = True
        self.turn = seat
        self.phase = "await_discard"
        self.last_draw = None
        self.pending = {}
        self.responses = {}

    def _advance_turn(self, from_seat: int):
        self.turn = (from_seat + 1) % 4
        self.phase = "await_discard"
        self.pending = {}
        self.responses = {}
        self._draw_for_turn()

    def declare_tsumo(self, seat: int) -> bool:
        if self.phase != "await_discard" or self.turn != seat:
            return False
        p = self.players[seat]
        if not mj.can_win(p.hand, p.exposed_meld_count):
            return False
        win_tile = self.last_draw
        self._win(seat, win_tile, self_draw=True, discarder=None)
        return True

    # ---- 結算 ----------------------------------------------------------------
    def _win_info(self, seat: int, win_tile: str, self_draw: bool,
                  discarder: Optional[int]) -> dict:
        """算出單一贏家的牌型/台數/亮牌資料。"""
        p = self.players[seat]
        # 食胡/搶槓：把胡的那張補進手牌，湊成完整胡牌手（自摸時已在手上）
        if not self_draw and win_tile:
            p.hand.append(win_tile)
            p.hand = mj.sort_hand(p.hand)
        ctx = self._win_context(seat, win_tile, self_draw, discarder)
        tai = score_hand(self, seat, win_tile, self_draw, ctx)
        return {
            "seat": seat,
            "win_type": ctx["win_type"],
            "tai": tai["total"],
            "tai_detail": tai["detail"],
            "menqing": p.is_menqing(),
            # 亮出整副牌（給所有人看）
            "reveal": {
                "hand": list(p.hand),
                "melds": [m.to_dict() for m in p.melds],
                "flowers": list(p.flowers),
            },
        }

    def _win(self, seats, win_tile: str, self_draw: bool, discarder: Optional[int]):
        """seats 可為單一座位或座位清單（一炮多響）。"""
        if isinstance(seats, int):
            seats = [seats]
        infos = [self._win_info(s, win_tile, self_draw, discarder) for s in seats]
        first = infos[0]
        self.phase = "over"
        self.result = {
            "type": "win",
            "winners": infos,               # 一炮多響：可能不只一位
            "multi": len(infos) > 1,
            "win_tile": win_tile,
            "self_draw": self_draw,
            "discarder": discarder,
            # 以下為單一贏家的相容欄位（取最近的一位）
            "winner": first["seat"],
            "win_type": first["win_type"],
            "tai": first["tai"],
            "tai_detail": first["tai_detail"],
            "menqing": first["menqing"],
            "reveal": first["reveal"],
        }

    def _win_context(self, seat, win_tile, self_draw, discarder) -> dict:
        """整理計分需要的情境旗標。"""
        p = self.players[seat]
        wt = mj.win_type(p.hand, p.exposed_meld_count)
        # 天/地/人胡：第一巡、無人吃碰槓
        first_round = (not self.any_claim) and len(p.discards) == 0
        tian = first_round and self_draw and seat == self.dealer and self.discard_count == 0
        di = (first_round and self_draw and seat != self.dealer
              and self.discard_count == ((seat - self.dealer) % 4))
        ren = (first_round and not self_draw and seat != self.dealer
               and self.discard_count <= 4)
        return {
            "win_type": wt or "normal",
            "discarder": discarder,
            "after_kong": self.after_kong and self_draw,
            "qianggang": self.qianggang,
            "haidi": self_draw and self.is_last_draw,
            "hedi": (not self_draw) and self.hedi_discard and not self.qianggang,
            "tianhu": tian,
            "dihu": di,
            "renhu": ren,
        }

    def _draw_game(self):
        self.phase = "over"
        self.result = {"type": "draw"}

    # ---- 給前端的狀態 --------------------------------------------------------
    def public_state(self) -> dict:
        return {
            "phase": self.phase,
            "turn": self.turn,
            "dealer": self.dealer,
            "round_wind": self.round_wind,
            "wall_left": max(0, len(self.wall)),
            "last_discard": self.last_discard,
            "players": [
                {
                    "seat": p.seat,
                    "hand_count": len(p.hand),
                    "melds": [m.to_dict() for m in p.melds],
                    "flowers": p.flowers,
                    "discards": p.discards,
                }
                for p in self.players
            ],
            "result": self.result,
        }

    def private_state(self, seat: int) -> dict:
        """只給該玩家看：自己的手牌 + 可執行動作。"""
        p = self.players[seat]
        data = {
            "your_seat": seat,
            "hand": p.hand,
            # 這一輪剛摸進來的牌：前端會把它獨立擺到最右邊，不排進手牌裡
            "drawn": (self.last_draw
                      if (self.phase == "await_discard" and self.turn == seat)
                      else None),
            "self_options": self.self_options(seat),
            "reactions": self.pending.get(seat, []),
        }
        # 若在反應階段，附上吃的組合供前端選
        if self.phase == "await_reaction" and seat in self.pending and self.last_discard:
            _, tile = self.last_discard
            if "chow" in self.pending[seat]:
                data["chow_options"] = mj.chow_options(p.hand, tile)
            data["react_tile"] = tile
        return data


# ---------------------------------------------------------------------------
# 台數表（可自行調整成你家的規則）
# ---------------------------------------------------------------------------
TAI = {
    "自摸": 1, "門清": 1, "不求人": 1, "莊家": 1, "連拉": 2,
    "圈風": 1, "門風": 1, "三元": 1,
    "平胡": 2, "對對胡": 4, "混一色": 4, "清一色": 8, "字一色": 16,
    "小三元": 4, "大三元": 8, "小四喜": 8, "大四喜": 16,
    "三暗刻": 2, "四暗刻": 5, "五暗刻": 8,
    "全求人": 2, "槓上開花": 1, "搶槓": 1, "海底": 1, "河底": 1, "獨聽": 1,
    "天胡": 24, "地胡": 16, "人胡": 8,
    "正花": 1, "花槓": 1,
    "哩咕哩咕": 8, "大不搭": 16, "小不搭": 8,
}
DRAGON_NAME = {"dz": "紅中", "df": "發財", "db": "白板"}


def _flower_tai(p: Player, seat: int, dealer: int) -> list[tuple[str, int]]:
    res = []
    sw = (seat - dealer) % 4                      # 門風：0東1南2西3北
    zheng = sum(1 for f in p.flowers if (int(f[1]) - 1) % 4 == sw)
    if zheng:
        res.append(("正花", TAI["正花"] * zheng))
    if all(f"f{i}" in p.flowers for i in range(1, 5)):
        res.append(("花槓(春夏秋冬)", TAI["花槓"]))
    if all(f"f{i}" in p.flowers for i in range(5, 9)):
        res.append(("花槓(梅蘭菊竹)", TAI["花槓"]))
    return res


def _structure_tai(game: Game, seat: int, concealed: list[str],
                   exposed: list[Meld], win_tile: str, self_draw: bool) -> list[tuple[str, int]]:
    """標準牌型：枚舉所有拆法，取台數最高的一種結構台。"""
    need = 5 - len(exposed)
    win_idx = mj.KIND_INDEX[win_tile]

    # 亮出的面子分類：('pung'/'chow', idx, 是否暗刻)
    exp = []
    for m in exposed:
        if m.kind == "chow":
            low = min(m.tiles, key=lambda t: mj.KIND_INDEX[t])
            exp.append(("chow", mj.KIND_INDEX[low], False))
        elif m.kind == "ankong":
            exp.append(("pung", mj.KIND_INDEX[m.tiles[0]], True))    # 暗槓＝暗刻
        else:  # pong / kong / addkong ＝ 明刻
            exp.append(("pung", mj.KIND_INDEX[m.tiles[0]], False))

    # 聽牌張數（判斷平胡兩面 / 獨聽），與拆法無關，先算一次
    pre = list(concealed)
    if win_tile in pre:
        pre.remove(win_tile)
    waits = mj.winning_tiles(pre, len(exposed)) if len(pre) == need * 3 + 1 else []
    dan_ting = (len(waits) == 1)
    liang_mian = (len(waits) >= 2)

    best, best_total = [], -1
    for pair, melds in mj.iter_decompositions(concealed, need):
        cur: list[tuple[str, int]] = []

        def a(n, t):
            if t:
                cur.append((n, t))

        all_pungs = []   # (idx, 是否暗刻)
        chows = 0
        for kind, idx in melds:
            if kind == "pung":
                is_conc = not (not self_draw and idx == win_idx)  # 食胡點成的刻＝明刻
                all_pungs.append((idx, is_conc))
            else:
                chows += 1
        for kind, idx, conc in exp:
            if kind == "pung":
                all_pungs.append((idx, conc))
            else:
                chows += 1

        pair_kind = mj.KINDS[pair]
        # 對對胡
        if len(all_pungs) == 5:
            a("對對胡", TAI["對對胡"])
        # 暗刻數
        anke = sum(1 for _, conc in all_pungs if conc)
        if anke == 3:
            a("三暗刻", TAI["三暗刻"])
        elif anke == 4:
            a("四暗刻", TAI["四暗刻"])
        elif anke >= 5:
            a("五暗刻", TAI["五暗刻"])
        # 三元
        dragons = [mj.KINDS[idx] for idx, _ in all_pungs if mj.KINDS[idx] in mj.DRAGONS]
        if len(dragons) == 3:
            a("大三元", TAI["大三元"])
        elif len(dragons) == 2 and pair_kind in mj.DRAGONS:
            a("小三元", TAI["小三元"])
        else:
            for d in dragons:
                a(DRAGON_NAME[d], TAI["三元"])
        # 四喜 / 風牌
        wind_pungs = [mj.KINDS[idx] for idx, _ in all_pungs if mj.KINDS[idx] in mj.WINDS]
        seat_wind = SEAT_WINDS[(seat - game.dealer) % 4]
        if len(wind_pungs) == 4:
            a("大四喜", TAI["大四喜"])
        elif len(wind_pungs) == 3 and pair_kind in mj.WINDS:
            a("小四喜", TAI["小四喜"])
        else:
            if game.round_wind in wind_pungs:
                a("圈風", TAI["圈風"])
            if seat_wind in wind_pungs:
                a("門風", TAI["門風"])
        # 全求人：五組全靠別人 + 食胡
        if len(exposed) == 5 and not self_draw and all(m.from_seat is not None for m in exposed):
            a("全求人", TAI["全求人"])
        # 平胡：全順、將非字牌、兩面聽，且要「無自摸、無花」
        if (chows == 5 and pair_kind not in mj.HONORS and liang_mian
                and not self_draw and not game.players[seat].flowers):
            a("平胡", TAI["平胡"])
        # 獨聽
        if dan_ting:
            a("獨聽", TAI["獨聽"])

        t = sum(x for _, x in cur)
        if t > best_total:
            best_total, best = t, cur
    return best


def score_hand(game: Game, seat: int, win_tile: str, self_draw: bool,
               ctx: Optional[dict] = None) -> dict:
    if ctx is None:
        ctx = {"win_type": mj.win_type(game.players[seat].hand,
                                       game.players[seat].exposed_meld_count) or "normal"}
    p = game.players[seat]
    exposed = p.melds
    concealed = list(p.hand)
    wt = ctx.get("win_type", "normal")
    detail: list[tuple[str, int]] = []

    def add(name, t):
        if t:
            detail.append((name, int(t)))

    # 所有牌（手牌＋亮牌，不含花）→ 一色判斷
    all_tiles = list(concealed)
    for m in exposed:
        all_tiles += m.tiles

    # ---- 通用台 ----
    if self_draw:
        add("自摸", TAI["自摸"])
    if p.is_menqing():
        add("門清", TAI["門清"])
        if self_draw:
            add("不求人", TAI["不求人"])   # 門清一摸三＝門清1＋自摸1＋不求人1
    # 莊家台：只要莊家有關就算 —— 莊家胡牌、莊家放槍、或別人自摸（莊家也要付）。
    # 唯一不算的情況是「閒家放槍給閒家」（莊家沒付錢也沒胡）。
    _discarder = ctx.get("discarder")
    if seat == game.dealer:
        add("莊家", TAI["莊家"])
    elif self_draw:
        add("莊家", TAI["莊家"])              # 閒家自摸 → 莊家也要付
    elif _discarder == game.dealer:
        add("莊家放槍", TAI["莊家"])
    if game.dealer_streak > 0:
        add(f"連{game.dealer_streak}拉{game.dealer_streak}", TAI["連拉"] * game.dealer_streak)
    for nm, t in _flower_tai(p, seat, game.dealer):
        add(nm, t)

    # 一色
    idxs = [mj.KIND_INDEX[t] for t in all_tiles]
    suited = {mj.idx_suit(i) for i in idxs if not mj.idx_is_honor(i)}
    has_honor = any(mj.idx_is_honor(i) for i in idxs)
    if not suited and has_honor:
        add("字一色", TAI["字一色"])
    elif len(suited) == 1 and not has_honor:
        add("清一色", TAI["清一色"])
    elif len(suited) == 1 and has_honor:
        add("混一色", TAI["混一色"])

    # 情境台
    if ctx.get("after_kong"):
        add("槓上開花", TAI["槓上開花"])
    if ctx.get("qianggang"):
        add("搶槓", TAI["搶槓"])
    if ctx.get("haidi"):
        add("海底摸月", TAI["海底"])
    if ctx.get("hedi"):
        add("河底撈魚", TAI["河底"])
    if ctx.get("tianhu"):
        add("天胡", TAI["天胡"])
    if ctx.get("dihu"):
        add("地胡", TAI["地胡"])
    if ctx.get("renhu"):
        add("人胡", TAI["人胡"])

    # ---- 牌型台 ----
    if wt == "liguligu":
        add("哩咕哩咕(全對)", TAI["哩咕哩咕"])
    elif wt == "shiliubuda":
        if mj.shiliubuda_tier(concealed) == "big":
            add("大不搭", TAI["大不搭"])
        else:
            add("小不搭", TAI["小不搭"])
    else:
        for nm, t in _structure_tai(game, seat, concealed, exposed, win_tile, self_draw):
            add(nm, t)

    total = sum(t for _, t in detail)
    if total == 0:
        detail.append(("胡牌", 0))
    return {"total": total, "detail": detail}


# ---------------------------------------------------------------------------
# 隨機自我對局測試：確保狀態機能跑到終局不崩潰
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def random_playout(seed):
        g = Game(dealer=0, seed=seed)
        g.start()
        rng = random.Random(seed * 7 + 1)
        steps = 0
        while g.phase != "over" and steps < 2000:
            steps += 1
            if g.phase == "await_discard":
                seat = g.turn
                opts = g.self_options(seat)
                if opts.get("tsumo") and rng.random() < 0.9:
                    g.declare_tsumo(seat)
                    continue
                # 偶爾暗槓
                if opts.get("ankong") and rng.random() < 0.3:
                    g.declare_ankong(seat, opts["ankong"][0])
                    continue
                # 隨機打一張
                hand = g.players[seat].hand
                g.discard(seat, rng.choice(hand))
            elif g.phase == "await_reaction":
                # 每個有反應權的人隨機決定
                for s in list(g.pending.keys()):
                    if s in g.responses:
                        continue
                    acts = g.pending[s]
                    if "hu" in acts and rng.random() < 0.95:
                        g.claim(s, "hu")
                        break
                    choice = rng.choice(acts + ["pass", "pass"])
                    if choice == "chow":
                        _, tile = g.last_discard
                        co = mj.chow_options(g.players[s].hand, tile)
                        g.claim(s, "chow", list(co[0]) if co else None)
                    else:
                        g.claim(s, choice)
                    if g.phase != "await_reaction":
                        break
                else:
                    continue
        return g.phase, (g.result or {}).get("type"), steps

    wins = draws = stuck = 0
    for seed in range(300):
        phase, rtype, steps = random_playout(seed)
        if phase != "over":
            stuck += 1
            print(f"  seed {seed} 卡住！steps={steps}")
        elif rtype == "win":
            wins += 1
        else:
            draws += 1
    print(f"隨機對局 300 局：胡 {wins}、流局 {draws}、卡住 {stuck}")
    assert stuck == 0, "有牌局卡住，狀態機有問題"
    # 展示一局結算
    g = Game(dealer=0, seed=42)
    g.start()
    print("開局莊家手牌：", [mj.name_of(t) for t in g.players[0].hand])
    print("狀態機自我測試通過 ✔")
