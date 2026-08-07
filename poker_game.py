# -*- coding: utf-8 -*-
"""
德州撲克 —— 單手牌局狀態機（伺服器權威）

一個 PokerTable 代表一桌（最多 8 人）。start_hand() 開始新的一手：
    發底牌 → preflop → flop → turn → river → showdown

不做任何網路 I/O；伺服器把 public_state()/private_state() 送給前端，
再把玩家動作轉成 act() 呼叫。
"""
from __future__ import annotations
import random
from typing import Optional

import poker as pk

MAX_SEATS = 8
PHASES = ("waiting", "preflop", "flop", "turn", "river", "showdown", "over")
STREETS = ("preflop", "flop", "turn", "river")


class PokerPlayer:
    def __init__(self, seat: int, name: str, stack: int):
        self.seat = seat
        self.name = name
        self.stack = stack
        self.hole: list[str] = []
        self.bet = 0             # 本輪已下注
        self.invested = 0        # 本手牌總投入（算邊池用）
        self.folded = False
        self.all_in = False
        self.acted = False       # 本輪是否已行動過
        self.sitting_out = False  # 沒籌碼→這手不參與
        self.last_action = ""    # 顯示用
        self.rebuy_total = 0     # 累計補碼（算淨輸贏用）

    def in_hand(self) -> bool:
        return not self.folded and not self.sitting_out

    def can_act(self) -> bool:
        return self.in_hand() and not self.all_in and self.stack > 0


class PokerTable:
    # 2-7 獎金：手拿 2 和 7 收池（攤牌或秀牌）時，每家額外付 2.5 個大盲
    BOUNTY_27_BB = 2.5
    # 炸彈彩池：每人先下 5 個大盲當底注，不打翻牌前，直接發翻牌
    BOMB_ANTE_BB = 5

    def __init__(self, small_blind: int = 10, big_blind: int = 20,
                 start_stack: int = 1000, seed: Optional[int] = None,
                 bounty_27: bool = True):
        self.rng = random.Random(seed)
        self.bounty_27 = bounty_27
        self.players: dict[int, PokerPlayer] = {}    # seat -> player
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.start_stack = start_stack
        self.button = 0
        self.phase = "waiting"
        self.deck: list[str] = []
        self.board: list[str] = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = big_blind
        self.to_act: Optional[int] = None
        self.last_aggressor: Optional[int] = None
        self.result: Optional[dict] = None
        self.hand_no = 0
        self.is_bomb = False          # 本手是否為炸彈彩池
        self.log: list[str] = []

    # ---- 座位 ----------------------------------------------------------------
    def seat_player(self, seat: int, name: str, stack: Optional[int] = None):
        self.players[seat] = PokerPlayer(seat, name,
                                         self.start_stack if stack is None else stack)

    def remove_player(self, seat: int):
        self.players.pop(seat, None)

    # ---- 補碼 ----------------------------------------------------------------
    REBUY_THRESHOLD = 300        # 籌碼低於此值可補碼

    def can_rebuy(self, seat: int) -> bool:
        """籌碼不足且沒有正在牌局中（避免中途改變籌碼破壞彩池計算）。"""
        p = self.players.get(seat)
        if not p or p.stack >= self.REBUY_THRESHOLD:
            return False
        idle = self.phase in ("waiting", "over") or p.sitting_out or p.folded
        return idle

    def rebuy(self, seat: int, amount: int) -> bool:
        if amount not in (500, 1000) or not self.can_rebuy(seat):
            return False
        p = self.players[seat]
        p.stack += amount
        p.rebuy_total += amount
        p.sitting_out = False
        self.log.append(f"{p.name} 補碼 {amount}")
        return True

    def active_seats(self) -> list[int]:
        """有籌碼、可參與下一手的座位（依座位號排序）。"""
        return sorted(s for s, p in self.players.items() if p.stack > 0)

    def _next_seat(self, seat: int, only_can_act=False) -> Optional[int]:
        """順時鐘找下一個仍在牌局中的座位。"""
        seats = sorted(self.players.keys())
        if not seats:
            return None
        i = seats.index(seat) if seat in seats else -1
        for k in range(1, len(seats) + 1):
            s = seats[(i + k) % len(seats)]
            p = self.players[s]
            if only_can_act:
                if p.can_act():
                    return s
            elif p.in_hand():
                return s
        return None

    # ---- 開一手 --------------------------------------------------------------
    def start_hand(self, bomb_pot: bool = False) -> bool:
        live = self.active_seats()
        if len(live) < 2:
            return False
        self.hand_no += 1
        self.is_bomb = bomb_pot
        self.deck = pk.make_deck()
        self.rng.shuffle(self.deck)
        self.board = []
        self.pot = 0
        self.result = None
        self.log = []

        for s, p in self.players.items():
            p.hole, p.bet, p.invested = [], 0, 0
            p.folded = p.all_in = p.acted = False
            p.last_action = ""
            p.sitting_out = p.stack <= 0        # 沒籌碼的這手不參與

        # 莊家鈕移到下一個有籌碼的人
        if self.hand_no > 1 or self.button not in live:
            nxt = [s for s in live if s > self.button] or live
            self.button = nxt[0]

        # 發底牌（每人 2 張）
        for _ in range(2):
            for s in live:
                self.players[s].hole.append(self.deck.pop())

        # 炸彈彩池：每人先下 5 個大盲底注，跳過翻牌前，直接發翻牌
        if bomb_pot:
            ante = self.big_blind * self.BOMB_ANTE_BB
            for s in live:
                self._post(s, ante, "炸彈底注")
            # 底注算「已投入」，但翻牌這一輪的下注要從 0 重新開始
            for p in self.players.values():
                p.bet = 0
                p.acted = False
            self.current_bet = 0
            self.min_raise = self.big_blind
            self.last_aggressor = None
            self.phase = "flop"
            self._deal_board()                      # 直接發 3 張公牌
            self.to_act = self._next_can_act(self.button)
            if self.to_act is None:
                self._finish_betting()
            return True

        # 下盲注：兩人時莊家是小盲；三人以上莊家下家是小盲
        if len(live) == 2:
            sb_seat = self.button
            bb_seat = self._next_live(self.button, live)
        else:
            sb_seat = self._next_live(self.button, live)
            bb_seat = self._next_live(sb_seat, live)
        self._post(sb_seat, self.small_blind, "小盲")
        self._post(bb_seat, self.big_blind, "大盲")

        self.current_bet = self.big_blind
        self.min_raise = self.big_blind
        self.last_aggressor = bb_seat
        self.phase = "preflop"
        # 翻牌前由大盲下家先說話
        self.to_act = self._next_can_act(bb_seat)
        if self.to_act is None:
            self._finish_betting()
        return True

    def _next_live(self, seat: int, live: list[int]) -> int:
        nxt = [s for s in live if s > seat]
        return (nxt or live)[0]

    def _post(self, seat: int, amount: int, label: str):
        p = self.players[seat]
        amt = min(amount, p.stack)
        p.stack -= amt
        p.bet += amt
        p.invested += amt
        self.pot += amt
        if p.stack == 0:
            p.all_in = True
        p.last_action = label
        self.log.append(f"{p.name} {label} {amt}")

    def _next_can_act(self, from_seat: int) -> Optional[int]:
        return self._next_seat(from_seat, only_can_act=True)

    # ---- 玩家可做的動作 -------------------------------------------------------
    def legal_actions(self, seat: int) -> dict:
        p = self.players.get(seat)
        if not p or self.to_act != seat or self.phase not in STREETS:
            return {}
        to_call = max(0, self.current_bet - p.bet)
        acts: dict = {"fold": True}
        if to_call == 0:
            acts["check"] = True
        else:
            acts["call"] = min(to_call, p.stack)
        # 加注：至少加到 current_bet + min_raise（籌碼不夠就只能 all-in）
        min_to = self.current_bet + self.min_raise
        max_to = p.bet + p.stack
        if max_to > self.current_bet:
            acts["raise"] = {"min": min(min_to, max_to), "max": max_to,
                             "is_allin_only": max_to < min_to}
        acts["allin"] = max_to
        return acts

    def act(self, seat: int, action: str, amount: Optional[int] = None) -> bool:
        if self.phase not in STREETS or self.to_act != seat:
            return False
        p = self.players.get(seat)
        if not p or not p.can_act():
            return False
        to_call = max(0, self.current_bet - p.bet)

        if action == "fold":
            p.folded = True
            p.last_action = "蓋牌"
        elif action == "check":
            if to_call != 0:
                return False
            p.last_action = "過牌"
        elif action == "call":
            if to_call == 0:
                return False
            self._put(p, min(to_call, p.stack))
            p.last_action = "跟注" if not p.all_in else "全下"
        elif action in ("raise", "allin"):
            target = p.bet + p.stack if action == "allin" else int(amount or 0)
            target = min(target, p.bet + p.stack)          # 不能超過自己所有籌碼
            if target <= self.current_bet and target < p.bet + p.stack:
                return False                                # 加注要比現有注大（除非 all-in）
            raise_size = target - self.current_bet
            if target > self.current_bet:
                # 合法加注 → 重開一輪，其他人要重新行動
                if raise_size >= self.min_raise or target == p.bet + p.stack:
                    if raise_size >= self.min_raise:
                        self.min_raise = raise_size
                    self.current_bet = target
                    self.last_aggressor = seat
                    for q in self.players.values():
                        if q.seat != seat and q.can_act():
                            q.acted = False
                else:
                    return False
            self._put(p, target - p.bet)
            p.last_action = "全下" if p.all_in else ("加注" if raise_size > 0 else "跟注")
        else:
            return False

        p.acted = True
        self.log.append(f"{p.name} {p.last_action}")
        self._advance()
        return True

    def _put(self, p: PokerPlayer, amount: int):
        amt = max(0, min(amount, p.stack))
        p.stack -= amt
        p.bet += amt
        p.invested += amt
        self.pot += amt
        if p.stack == 0:
            p.all_in = True

    # ---- 流程推進 ------------------------------------------------------------
    def _advance(self):
        alive = [p for p in self.players.values() if p.in_hand()]
        if len(alive) <= 1:
            return self._end_hand_no_showdown(alive[0] if alive else None)

        # 本輪是否結束：能行動的人都行動過、且注碼一致
        pending = [p for p in self.players.values()
                   if p.can_act() and (not p.acted or p.bet != self.current_bet)]
        if pending:
            nxt = self._next_can_act(self.to_act)
            # 從目前位置往後找第一個還需要行動的人
            for _ in range(MAX_SEATS + 1):
                if nxt is None:
                    break
                q = self.players[nxt]
                if not q.acted or q.bet != self.current_bet:
                    self.to_act = nxt
                    return
                nxt = self._next_can_act(nxt)
        self._finish_betting()

    def _finish_betting(self):
        """本輪結束 → 收注、發公牌或攤牌。"""
        for p in self.players.values():
            p.bet = 0
            p.acted = False
        self.current_bet = 0
        self.min_raise = self.big_blind

        # 還能行動的人少於 2 → 直接發完所有公牌攤牌
        can_act = [p for p in self.players.values() if p.can_act()]
        alive = [p for p in self.players.values() if p.in_hand()]
        if len(alive) <= 1:
            return self._end_hand_no_showdown(alive[0] if alive else None)

        idx = STREETS.index(self.phase)
        if len(can_act) <= 1:
            while len(self.board) < 5:
                self._deal_board()
            return self._showdown()

        if idx + 1 < len(STREETS):
            self.phase = STREETS[idx + 1]
            self._deal_board()
            self.to_act = self._next_can_act(self.button)
            if self.to_act is None:
                return self._finish_betting()
        else:
            self._showdown()

    def _deal_board(self):
        need = 3 if not self.board else 1
        for _ in range(need):
            if self.deck:
                self.board.append(self.deck.pop())

    # ---- 結算 ----------------------------------------------------------------
    def _build_pots(self) -> list[dict]:
        """依各人投入金額切出主池與邊池。"""
        levels = sorted({p.invested for p in self.players.values() if p.invested > 0})
        pots: list[dict] = []
        prev, carry = 0, 0
        for lv in levels:
            amount = 0
            for p in self.players.values():
                amount += max(0, min(p.invested, lv) - prev)
            eligible = [p.seat for p in self.players.values()
                        if p.in_hand() and p.invested >= lv]
            if amount > 0:
                if eligible:
                    pots.append({"amount": amount + carry, "eligible": eligible})
                    carry = 0
                else:
                    # 這一層只有蓋牌的人投過（例如兩人下大注後都蓋牌）→
                    # 沒有人有資格贏，錢併回下面的池，不能憑空消失
                    carry += amount
            prev = lv
        if carry:
            if pots:
                pots[-1]["amount"] += carry
            else:
                pots.append({"amount": carry, "eligible": []})
        # 合併相同資格的連續池，畫面比較好看
        merged: list[dict] = []
        for pot in pots:
            if merged and merged[-1]["eligible"] == pot["eligible"]:
                merged[-1]["amount"] += pot["amount"]
            else:
                merged.append(pot)
        return merged

    # ---- 2-7 獎金 -------------------------------------------------------------
    @staticmethod
    def has_27(hole: list[str]) -> bool:
        """底牌是不是一張 2 一張 7（花色不拘）。"""
        if len(hole) != 2:
            return False
        ranks = sorted(pk.rank_of(c) for c in hole)
        return ranks == [2, 7]

    def _apply_27_bounty(self, seat: int) -> Optional[dict]:
        """贏家手拿 2-7 → 這手有下場的其他人每人付 2.5 個大盲（籌碼不夠就付到底）。"""
        if not self.bounty_27:
            return None
        win = self.players.get(seat)
        if not win or not self.has_27(win.hole):
            return None
        each = int(round(self.big_blind * self.BOUNTY_27_BB))
        paid: dict[int, int] = {}
        for s, p in self.players.items():
            if s == seat or p.sitting_out:
                continue
            amt = min(each, p.stack)
            if amt <= 0:
                continue
            p.stack -= amt
            win.stack += amt
            paid[s] = amt
        if not paid:
            return None
        total = sum(paid.values())
        self.log.append(f"{win.name} 2-7 獎金 每家 {each}，共收 {total}")
        return {"seat": seat, "each": each, "total": total, "paid": paid,
                "hole": list(win.hole)}

    def show_cards(self, seat: int) -> bool:
        """沒攤牌就收池的贏家，可選擇秀牌（亮出後若是 2-7 就領獎金）。"""
        r = self.result
        if not r or r.get("type") != "fold_win":
            return False
        if seat not in (r.get("winners") or []) or r.get("shown_by_choice"):
            return False
        p = self.players.get(seat)
        if not p or not p.hole:
            return False
        r["shown"] = {seat: {"hole": list(p.hole), "best": [], "desc": "秀牌"}}
        r["shown_by_choice"] = True
        b = self._apply_27_bounty(seat)
        if b:
            r["bounty27"] = b
        return True

    def _end_hand_no_showdown(self, winner: Optional[PokerPlayer]):
        """其他人都蓋牌 → 直接收池，不用亮牌。"""
        self.phase = "over"
        payouts: dict[int, int] = {}
        if winner:
            winner.stack += self.pot
            payouts[winner.seat] = self.pot
        self.result = {
            "type": "fold_win",
            "winners": [winner.seat] if winner else [],
            "payouts": payouts,
            "pot": self.pot,
            "board": list(self.board),
            "shown": {},          # 不亮牌
        }
        self.pot = 0
        self.to_act = None

    def _showdown(self):
        self.phase = "showdown"
        pots = self._build_pots()
        alive = [p for p in self.players.values() if p.in_hand()]
        scores: dict[int, tuple] = {}
        best5: dict[int, list[str]] = {}
        for p in alive:
            sc, five = pk.best_of(p.hole + self.board)
            scores[p.seat] = sc
            best5[p.seat] = five

        payouts: dict[int, int] = {}
        pot_results = []
        for pot in pots:
            cand = [s for s in pot["eligible"] if s in scores]
            if not cand:
                continue
            top = max(scores[s] for s in cand)
            winners = [s for s in cand if scores[s] == top]
            share, rem = divmod(pot["amount"], len(winners))
            for i, s in enumerate(sorted(winners)):
                got = share + (1 if i < rem else 0)     # 零頭給座位小的
                self.players[s].stack += got
                payouts[s] = payouts.get(s, 0) + got
            pot_results.append({"amount": pot["amount"], "winners": winners})

        self.phase = "over"
        winner_seats = sorted({s for pr in pot_results for s in pr["winners"]})
        self.result = {
            "type": "showdown",
            "winners": winner_seats,
            "payouts": payouts,
            "pot": sum(p["amount"] for p in pots),
            "pots": pot_results,
            "board": list(self.board),
            "shown": {p.seat: {"hole": p.hole,
                               "best": best5[p.seat],
                               "desc": pk.describe(scores[p.seat])} for p in alive},
        }
        self.pot = 0
        self.to_act = None
        # 攤牌時牌已亮開 → 2-7 獎金自動生效
        for s in winner_seats:
            b = self._apply_27_bounty(s)
            if b:
                self.result["bounty27"] = b
                break

    # ---- 給前端的狀態 --------------------------------------------------------
    def settlement(self, start_stack: int) -> list[dict]:
        """遊戲結算：每人的買入、目前籌碼與淨輸贏（依淨輸贏排序）。"""
        rows = []
        for s, p in self.players.items():
            buyin = start_stack + p.rebuy_total
            rows.append({
                "seat": s, "name": p.name, "stack": p.stack,
                "buyin": buyin, "rebuy": p.rebuy_total,
                "net": p.stack - buyin,
            })
        return sorted(rows, key=lambda x: -x["net"])

    def public_state(self) -> dict:
        return {
            "phase": self.phase,
            "board": list(self.board),
            "pot": self.pot,
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "button": self.button,
            "to_act": self.to_act,
            "small_blind": self.small_blind,
            "big_blind": self.big_blind,
            "hand_no": self.hand_no,
            "is_bomb": self.is_bomb,
            "bomb_ante": self.big_blind * self.BOMB_ANTE_BB,
            "players": [
                {
                    "seat": p.seat, "name": p.name, "stack": p.stack,
                    "bet": p.bet, "invested": p.invested,
                    "folded": p.folded, "all_in": p.all_in,
                    "sitting_out": p.sitting_out,
                    "has_cards": bool(p.hole) and not p.folded and not p.sitting_out,
                    "last_action": p.last_action,
                    "rebuy_total": p.rebuy_total,
                }
                for p in sorted(self.players.values(), key=lambda x: x.seat)
            ],
            "result": self.result,
        }

    def private_state(self, seat: int) -> dict:
        p = self.players.get(seat)
        return {
            "your_seat": seat,
            "hole": list(p.hole) if p else [],
            "actions": self.legal_actions(seat),
            "to_call": max(0, self.current_bet - p.bet) if p else 0,
            "stack": p.stack if p else 0,
            "can_rebuy": self.can_rebuy(seat),
            "rebuy_options": [500, 1000],
            # 沒攤牌就收池的贏家，可以選擇秀牌（亮 2-7 才能領獎金）
            "can_show": bool(
                self.result and self.result.get("type") == "fold_win"
                and not self.result.get("shown_by_choice")
                and seat in (self.result.get("winners") or [])),
            "bounty_27": self.bounty_27,
            "bounty_each": int(round(self.big_blind * self.BOUNTY_27_BB)),
        }


# ---------------------------------------------------------------------------
# 隨機自我對局測試
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def playout(seed, n_players):
        rng = random.Random(seed)
        t = PokerTable(small_blind=10, big_blind=20, start_stack=1000, seed=seed)
        for s in range(n_players):
            t.seat_player(s, f"P{s}")
        total_before = sum(p.stack for p in t.players.values())
        hands, steps = 0, 0
        while len(t.active_seats()) >= 2 and hands < 30:
            if not t.start_hand():
                break
            hands += 1
            while t.phase in STREETS and steps < 5000:
                steps += 1
                seat = t.to_act
                if seat is None:
                    break
                acts = t.legal_actions(seat)
                if not acts:
                    break
                r = rng.random()
                if "check" in acts and r < 0.5:
                    t.act(seat, "check")
                elif "call" in acts and r < 0.75:
                    t.act(seat, "call")
                elif "raise" in acts and r < 0.9:
                    rr = acts["raise"]
                    amt = rng.randint(rr["min"], max(rr["min"], min(rr["max"], rr["min"] * 2)))
                    if not t.act(seat, "raise", amt):
                        t.act(seat, "fold")
                else:
                    t.act(seat, "fold")
            total_after = sum(p.stack for p in t.players.values()) + t.pot
            assert total_after == total_before, \
                f"籌碼不守恆！seed={seed} 前={total_before} 後={total_after}"
        return hands, t

    total_hands = 0
    for seed in range(120):
        for n in (2, 3, 5, 8):
            h, t = playout(seed, n)
            total_hands += h
            assert t.phase in ("over", "waiting"), f"seed={seed} n={n} 卡在 {t.phase}"
    print(f"隨機對局：{total_hands} 手全部跑完，籌碼守恆、無卡住 ✔")

    # 邊池：短碼 all-in
    t = PokerTable(10, 20, 1000, seed=1)
    t.seat_player(0, "A", 100)
    t.seat_player(1, "B", 1000)
    t.seat_player(2, "C", 1000)
    t.start_hand()
    while t.phase in STREETS:
        s = t.to_act
        if s is None:
            break
        acts = t.legal_actions(s)
        if "allin" in acts and t.players[s].stack > 0:
            t.act(s, "allin")
        elif "call" in acts:
            t.act(s, "call")
        elif "check" in acts:
            t.act(s, "check")
        else:
            t.act(s, "fold")
    assert t.result is not None
    total = sum(p.stack for p in t.players.values())
    assert total == 2100, f"籌碼總量應為 2100，實得 {total}"
    print("邊池／全下：籌碼守恆 ✔　結果:", t.result["type"],
          "payouts:", t.result["payouts"])
    print("poker_game.py 自我測試通過 ✔")
