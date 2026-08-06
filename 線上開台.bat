@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   線上麻將 - 一鍵開台
echo ============================================================
echo.
echo 正在開啟兩個視窗：
echo   1) 麻將伺服器
echo   2) 對外通道 cloudflared
echo.
echo 稍等幾秒，第 2 個視窗會出現一行：
echo     https://xxxx-xxxx.trycloudflare.com
echo 把那行網址貼給朋友，他們用瀏覽器打開就能加入！
echo.
echo （要結束時，把這兩個視窗關掉即可）
echo ============================================================

start "麻將伺服器（勿關）" cmd /k python server.py
timeout /t 3 >nul
start "對外通道：把下面的 trycloudflare 網址貼給朋友" cmd /k ""C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8080"

echo.
echo 已開啟。請看「對外通道」視窗裡的 https://...trycloudflare.com 網址。
pause
