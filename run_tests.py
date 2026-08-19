# -*- coding: utf-8 -*-
"""
跑完整測試套件：python run_tests.py [關鍵字]

以前要先自己開 server.py、再一個個手動跑 test_*.py，很容易漏跑或忘了
伺服器還開著舊版程式碼。這支會自己在隨機埠起一個乾淨的伺服器，
把 MJ_TEST_URL 傳給連線測試，跑完再收掉。

  python run_tests.py            跑全部
  python run_tests.py poker      只跑檔名含 poker 的
  python run_tests.py --fast     跳過慢的（逾時類要等真實倒數）
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
PY = sys.executable

# 不需要伺服器的純測試（引擎、計分）
PURE = ["mahjong.py", "game.py", "poker.py", "poker_game.py",
        "test_scoring.py", "test_rounds.py", "test_priority.py",
        "test_poker_bounty.py", "test_poker_bomb.py", "test_poker_join.py"]

# 需要連線到伺服器的測試（＝用到 ws_test_util 的）
LIVE = ["test_client.py", "test_leave_restart.py", "test_priority_live.py",
        "test_hidden_reaction.py", "test_reconnect.py", "test_voice.py",
        "test_poker_server.py", "test_poker_show_rebuy.py",
        "test_wrong_game_msg.py", "test_timeout.py"]

# 要等真實倒數，--fast 會跳過
SLOW = {"test_timeout.py", "test_priority_live.py"}


def check_coverage() -> list[str]:
    """新增的 test_*.py 若忘了歸類就會漏跑，開跑前先擋下來。

    連線測試＝有用到 ws_test_util（或直接用 websockets）的，
    這比人工維護清單可靠。
    """
    problems = []
    for f in sorted(HERE.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        needs_server = "ws_test_util" in src or "import websockets" in src
        listed_pure, listed_live = f.name in PURE, f.name in LIVE
        if not listed_pure and not listed_live:
            problems.append(f"{f.name} 沒被列進 PURE 或 LIVE（會漏跑）")
        elif needs_server and listed_pure:
            problems.append(f"{f.name} 需要伺服器卻被列在 PURE")
        elif not needs_server and listed_live:
            problems.append(f"{f.name} 不需要伺服器卻被列在 LIVE")
    return problems


def server_crashes(log_path: Path) -> list[str]:
    """從伺服器日誌挑出未處理例外的那一行（Traceback 的最後一行）。"""
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    out, in_tb = [], False
    for line in text.splitlines():
        if line.startswith("Traceback ("):
            in_tb = True
            continue
        if in_tb and line and not line[0].isspace():
            out.append(line.strip())
            in_tb = False
    # 同樣的例外會重複很多次，收斂成不重複的
    seen, uniq = set(), []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(port: int, timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


def run_one(name: str, env: dict) -> tuple[bool, str, float]:
    t0 = time.time()
    p = subprocess.run([PY, str(HERE / name)], cwd=HERE, env=env,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode == 0, (p.stdout or "") + (p.stderr or ""), time.time() - t0


def main() -> int:
    problems = check_coverage()
    if problems:
        print("測試清單有問題：")
        for p in problems:
            print(f"  - {p}")
        return 1

    args = [a for a in sys.argv[1:]]
    fast = "--fast" in args
    keywords = [a for a in args if not a.startswith("--")]

    def wanted(name):
        if fast and name in SLOW:
            return False
        return not keywords or any(k in name for k in keywords)

    pure = [f for f in PURE if wanted(f)]
    live = [f for f in LIVE if wanted(f)]

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    results: list[tuple[str, bool, float]] = []
    failed_output: list[tuple[str, str]] = []

    def report(name, ok, out, secs):
        results.append((name, ok, secs))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<26} {secs:5.1f}s", flush=True)
        if not ok:
            failed_output.append((name, out))

    if pure:
        print(f"── 純引擎測試（{len(pure)}）" + " " * 8)
        for f in pure:
            report(f, *run_one(f, env))

    proc = None
    if live:
        port = free_port()
        print(f"\n── 連線測試（{len(live)}）：在埠 {port} 起臨時伺服器")
        senv = dict(env, PORT=str(port))
        # 伺服器的輸出寫檔，不要用 PIPE：沒人讀的管線寫滿 64KB 就會
        # 把伺服器整個卡住，症狀是「healthz 通得過但 WebSocket 握手逾時」。
        log = HERE / "_server_test.log"
        logf = log.open("w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen([PY, str(HERE / "server.py")], cwd=HERE, env=senv,
                                stdout=logf, stderr=subprocess.STDOUT)
        try:
            if not wait_healthy(port):
                logf.flush()
                why = log.read_text(encoding='utf-8', errors='replace')[-2000:]
                print('  伺服器起不來，連線測試全部跳過')
                print(why)
                return 1
            lenv = dict(env, MJ_TEST_URL=f"ws://127.0.0.1:{port}/ws")
            for f in live:
                report(f, *run_one(f, lenv))
            # 伺服器端的例外不會讓客戶端測試失敗——訊息處理器一炸，
            # 該連線直接斷掉，測試往往只是變慢然後照樣「通過」。
            # 明確把它當成失敗，否則這種 bug 會靜悄悄溜過去。
            logf.flush()
            crashes = server_crashes(log)
            if crashes:
                print()
                print("  FAIL  伺服器端有 %d 次未處理例外：" % len(crashes))
                for line in crashes[:5]:
                    print(f"        {line}")
                results.append(("(伺服器例外)", False, 0.0))
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                logf.close()

    total = len(results)
    bad = [n for n, ok, _ in results if not ok]
    secs = sum(s for _, _, s in results)
    print(f"\n{'=' * 46}")
    if bad:
        for name, out in failed_output:
            print(f"\n─── {name} 的輸出 ───")
            print("\n".join(out.strip().splitlines()[-25:]))
        print(f"\n{len(bad)}/{total} 失敗：{', '.join(bad)}　（{secs:.0f}s）")
        return 1
    print(f"全部 {total} 項通過（{secs:.0f}s）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
