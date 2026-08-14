"use strict";
// 牌面繪製（tileEl / tileName / 配色）已抽到 tiles.js，index.html 先載入它。

// ---- 狀態 ----
let ws=null, mySeat=null, roomCode=null, token=null;
let lastPublic=null, lastPrivate=null;
// 音效用：記住上一次的牌局狀態，用來偵測「發生了什麼事」
let sfxPrev=null, curHandNo=null, hostSeat=0;

// ---- 行動倒數 ----
// 伺服器只在狀態更新時給「剩餘毫秒」，前端自己往下數，才不用一直問伺服器
let deadlineAt=null, turnTotalMs=20000, lastTickSec=null;
function setDeadline(ms, totalSec){
  deadlineAt = (ms===null || ms===undefined) ? null : Date.now()+ms;
  if(totalSec) turnTotalMs = totalSec*1000;
  if(deadlineAt===null) lastTickSec=null;
}
function updateTimerUI(){
  const els=document.querySelectorAll(".turn-timer");
  if(deadlineAt===null){ els.forEach(e=>e.style.display="none"); return; }
  const left=Math.max(0, deadlineAt-Date.now());
  const pct=Math.max(0, Math.min(1, left/turnTotalMs));
  const secs=Math.ceil(left/1000);
  const urgent=left<=5000;
  els.forEach(e=>{
    e.style.display="";
    e.classList.toggle("urgent", urgent);
    const bar=e.querySelector(".tt-bar"); if(bar) bar.style.width=(pct*100)+"%";
    const num=e.querySelector(".tt-num"); if(num) num.textContent=secs;
  });
  // 只在「輪到我」且剩 5 秒內時，每秒嗶一聲提醒
  if(urgent && secs>0 && secs!==lastTickSec && isMyTurnNow()){
    lastTickSec=secs;
    SFX.play("draw_tile");
  }
}
function isMyTurnNow(){
  const pub=lastPublic, pri=lastPrivate;
  if(!pub) return false;
  if(gameType==="poker") return pub.to_act===mySeat;
  return (pub.phase==="await_discard" && pub.turn===mySeat) ||
         (pub.phase==="await_reaction" && (pri?.reactions||[]).length>0);
}
setInterval(updateTimerUI, 200);

function timerEl(){
  const d=document.createElement("div");
  d.className="turn-timer";
  d.innerHTML='<span class="tt-num"></span><span class="tt-track"><span class="tt-bar"></span></span>';
  return d;
}
let gameType="mahjong";          // "mahjong" | "poker"
let pokerPrev=null;

// 送出德州下注動作（poker_ui.js 會呼叫）
function pokerAct(action, amount){
  send({t:"poker_act", action, amount});
}

// 德州音效：依階段/動作變化播提示
function playPokerSounds(pub){
  const snap={phase:pub.phase, pot:pub.pot, to_act:pub.to_act,
              board:(pub.board||[]).length};
  if(pokerPrev){
    if(snap.board>pokerPrev.board) SFX.play("discard");        // 發公牌
    if(snap.pot>pokerPrev.pot) SFX.play("chow");               // 有人下注
    if(snap.phase==="over" && pokerPrev.phase!=="over") SFX.play("hu");
    else if(snap.to_act===mySeat && pokerPrev.to_act!==mySeat) SFX.play("your_turn");
  }
  pokerPrev=snap;
}

// 比較新舊狀態，播對應音效
function playStateSounds(pub, pri){
  const prev=sfxPrev;
  const snap={
    handNo: null,
    discards: pub.players.map(p=>p.discards.length),
    melds: pub.players.map(p=>p.melds.length),
    meldKinds: pub.players.map(p=>p.melds.map(m=>m.kind)),
    flowers: pub.players.map(p=>p.flowers.length),
    phase: pub.phase, turn: pub.turn,
    over: pub.phase==="over",
  };
  if(prev){
    // 有人吃/碰/槓（亮牌數變多）→ 音效 + 大字提示
    const NAME_OF={chow:"吃", pong:"碰", kong:"槓", ankong:"暗槓", addkong:"加槓"};
    for(let i=0;i<4;i++){
      if(snap.melds[i] > prev.melds[i]){
        const kinds=pub.players[i].melds;
        const k=kinds[kinds.length-1]?.kind;
        SFX.play(k==="chow"?"chow": (k==="pong"?"pong":"kong"));
        showCall(NAME_OF[k]||"碰", pub.players[i].name, i===mySeat,
                 k==="chow"?"call-chow":(k==="pong"?"call-pong":"call-kong"));
      }else if(snap.melds[i]===prev.melds[i]){
        // 加槓：組數沒變，但某一組從「碰」變成「加槓」。
        // 只認這個轉變，避免狀態重送／重連時整串比對而誤報。
        const before=prev.meldKinds[i]||[], now=snap.meldKinds[i]||[];
        const upgraded=now.some((k,idx)=> k==="addkong" && before[idx]==="pong");
        if(upgraded){
          SFX.play("kong");
          showCall("加槓", pub.players[i].name, i===mySeat, "call-kong");
        }
      }
      if(snap.flowers[i] > prev.flowers[i]) SFX.play("flower");
      // 有人打牌
      if(snap.discards[i] > prev.discards[i]) SFX.play("discard");
    }
    // 結算
    if(snap.over && !prev.over){
      const r=pub.result;
      if(!r){ /* nothing */ }
      else if(r.type==="draw") SFX.play("draw_game");
      else{
        const winners=r.winners||[{seat:r.winner}];
        const iWon=winners.some(w=>w.seat===mySeat);
        if(winners.length>1) SFX.play("multi_hu");
        else if(iWon) SFX.play("hu");
        else if(r.discarder===mySeat) SFX.play("lose");
        else SFX.play("hu");
        const names=winners.map(w=>pub.players[w.seat]?.name||"").join("、");
        showCall(r.self_draw?"自摸":"胡", names, iWon, "call-hu", 1800);
      }
    }
    // 輪到我出牌
    else if(pub.phase==="await_discard" && pub.turn===mySeat &&
            !(prev.phase==="await_discard" && prev.turn===mySeat)){
      SFX.play("your_turn");
    }
    // 我可以吃碰槓胡（有動作可選）
    else if(pub.phase==="await_reaction" && (pri.reactions||[]).length &&
            prev.phase!=="await_reaction"){
      SFX.play("your_turn");
    }
  }
  sfxPrev=snap;
}

// 手機在剛進牌桌 / 轉向 / 網址列收合時，可視高度會變動；
// 多重畫幾次確保版面用的是最終尺寸（否則手牌可能被裁在畫面外）。
function scheduleRelayout(){
  [0, 150, 400, 900].forEach(d=> setTimeout(()=>{ if(lastPublic) renderTable(); }, d));
}
// 轉向／網址列收合會連發很多次 resize，做防抖避免狂重繪拖慢畫面
let _relayoutT=null;
function relayoutSoon(){
  clearTimeout(_relayoutT);
  _relayoutT=setTimeout(()=>{ if(lastPublic && gameType!=="poker") renderTable(); }, 120);
}
["resize","orientationchange"].forEach(ev=>
  window.addEventListener(ev, relayoutSoon));
if(window.visualViewport){
  window.visualViewport.addEventListener("resize", relayoutSoon);
}

// ---- 畫面切換 ----
function show(id){
  document.querySelectorAll(".screen").forEach(s=>s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

// ---- WebSocket ----
function connect(){
  const proto = location.protocol==="https:" ? "wss":"ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = ()=>{
    // 嘗試自動重連
    const saved = JSON.parse(localStorage.getItem("mahjong_session")||"null");
    if(saved && saved.code && saved.token){
      roomCode=saved.code; token=saved.token;
      send({t:"reconnect", code:saved.code, token:saved.token});
    }
  };
  ws.onmessage = (e)=> handle(JSON.parse(e.data));
  ws.onclose = ()=>{ setTimeout(connect, 1500); };  // 斷線自動重連
}
function send(obj){ if(ws && ws.readyState===1) ws.send(JSON.stringify(obj)); }

function handle(m){
  switch(m.t){
    case "joined":
      mySeat=m.seat; roomCode=m.code; token=m.token;
      if(m.game_type) setGameType(m.game_type);   // 加入別人的房：自動切成該房的遊戲
      localStorage.setItem("mahjong_session", JSON.stringify({code:roomCode, token}));
      document.getElementById("room-code").textContent=roomCode;
      show("waiting");
      break;
    case "room":
      hostSeat = m.host_seat ?? 0;
      if(m.voice_peers){ Voice.setSeat(mySeat); Voice.syncPeers(m.voice_peers); }
      renderWaiting(m);
      // 牌局被中止（有人離開／尚未開始）→ 從牌桌回到等待室
      if(!m.started && document.getElementById("table").classList.contains("active")){
        document.getElementById("result-overlay").classList.remove("show");
        lastPublic=null; lastPrivate=null; sfxPrev=null;
        show("waiting");
      }
      break;
    case "left":
      backToLobby();
      break;
    case "notice":
      showNotice(m.msg);
      break;
    case "voice_peers":
      Voice.setSeat(mySeat);
      Voice.syncPeers(m.peers);
      break;
    case "rtc":
      Voice.signal(m);
      break;
    case "dealer_roll":
      showDealerRoll(m);
      break;
    case "state":
      if(m.game_type==="poker" || gameType==="poker"){
        lastPublic=m.public; lastPrivate=m.private;
        setDeadline(m.public.deadline_ms, m.public.turn_seconds);
        show("poker");
        renderPoker(m.public, m.private, mySeat);
        playPokerSounds(m.public);
        break;
      }
      if(m.hand_no!==undefined && m.hand_no!==curHandNo){ curHandNo=m.hand_no; sfxPrev=null; }
      lastPublic=m.public; lastPrivate=m.private;
      setDeadline(m.public.deadline_ms, m.public.turn_seconds);
      {
        const first = !document.getElementById("table").classList.contains("active");
        show("table");
        renderTable();
        // 第一次進牌桌：手機的網址列/安全區此時可能還在變動，
        // 稍後再重畫一次，避免版面（尤其手牌）算在舊尺寸上被裁掉
        if(first) scheduleRelayout();
      }
      playStateSounds(m.public, m.private);
      break;
    case "reconnect_failed":
      // 伺服器重啟或房間已結束：清掉舊紀錄，回大廳重新開始
      localStorage.removeItem("mahjong_session");
      mySeat=null; roomCode=null; token=null;
      lastPublic=null; lastPrivate=null; sfxPrev=null;
      show("lobby");
      flashError(m.msg||"連線已重置，請重新開房");
      break;
    case "error":
      flashError(m.msg);
      break;
  }
}

// 開局擲骰決定莊家：骰子滾動動畫 + 結果
const DICE_FACE=["","⚀","⚁","⚂","⚃","⚄","⚅"];
function showDealerRoll(m){
  let el=document.getElementById("dealer-roll");
  if(!el){
    el=document.createElement("div"); el.id="dealer-roll";
    el.innerHTML='<div class="dr-title">擲骰決定莊家</div>'+
                 '<div class="dr-dice"></div><div class="dr-res"></div>';
    document.body.appendChild(el);
  }
  const diceEl=el.querySelector(".dr-dice"), resEl=el.querySelector(".dr-res");
  resEl.textContent="";
  el.classList.add("show");
  SFX.play("discard");
  // 滾動動畫
  let n=0;
  const spin=setInterval(()=>{
    diceEl.textContent=[0,0,0].map(()=>DICE_FACE[1+Math.floor(Math.random()*6)]).join(" ");
    if(++n>8){
      clearInterval(spin);
      diceEl.textContent=m.dice.map(d=>DICE_FACE[d]).join(" ");
      resEl.innerHTML=`${m.dice.join(" + ")} = <b>${m.total}</b><br>`+
                      `<span class="dr-dealer">${escapeHtml(m.dealer_name||"")} 做莊</span>`;
      SFX.play("kong");
    }
  }, 90);
  clearTimeout(showDealerRoll._t);
  showDealerRoll._t=setTimeout(()=>el.classList.remove("show"), 2600);
}

// 吃／碰／槓／胡：畫面中央跳出大字（自己做的會多一圈金框）
function showCall(word, who, isMe, cls, ms=1200){
  let el=document.getElementById("call-fx");
  if(!el){
    el=document.createElement("div"); el.id="call-fx";
    document.body.appendChild(el);
  }
  el.className=(cls||"")+(isMe?" mine":"");
  el.innerHTML=`<div class="call-word">${escapeHtml(word)}</div>`+
               `<div class="call-who">${escapeHtml(who||"")}</div>`;
  // 重新觸發動畫
  el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  clearTimeout(showCall._t);
  showCall._t=setTimeout(()=>el.classList.remove("show"), ms);
}

// 全畫面短暫提示（例如「有玩家離開，本局中止」）
function showNotice(msg){
  if(!msg) return;
  let el=document.getElementById("notice-toast");
  if(!el){
    el=document.createElement("div"); el.id="notice-toast";
    document.body.appendChild(el);
  }
  el.textContent=msg;
  el.classList.add("show");
  clearTimeout(showNotice._t);
  showNotice._t=setTimeout(()=>el.classList.remove("show"), 3200);
}

function flashError(msg){
  const el=document.getElementById("lobby-err");
  if(document.getElementById("lobby").classList.contains("active")){
    el.textContent=msg; setTimeout(()=>el.textContent="",3000);
  }else{
    // 桌面上用 action-bar 短暫提示
    const bar=document.getElementById("action-bar");
    const tip=document.createElement("div");
    tip.textContent=msg; tip.style.cssText="background:#000a;padding:8px 16px;border-radius:20px";
    bar.appendChild(tip); setTimeout(()=>tip.remove(),2500);
  }
}

// ---- 大廳 ----
// 大廳：選遊戲類型
function setGameType(g){
  gameType = (g==="poker") ? "poker" : "mahjong";
  document.querySelectorAll(".gp").forEach(b=>
    b.classList.toggle("active", b.dataset.game===gameType));
  const poker = gameType==="poker";
  document.getElementById("lobby-title").textContent = poker ? "🃏 德州撲克" : "🀄 線上麻將";
  document.getElementById("lobby-sub").textContent =
    poker ? "最多 8 人 · 跟朋友連線對戰" : "台灣 16 張 · 跟朋友連線對戰";
  const pc=document.getElementById("poker-cfg"), mc=document.getElementById("mj-cfg");
  if(pc) pc.style.display = poker ? "" : "none";
  if(mc) mc.style.display = poker ? "none" : "";
}
document.querySelectorAll(".gp").forEach(b=>
  b.onclick=()=> setGameType(b.dataset.game));

document.getElementById("btn-create").onclick=()=>{
  const name=document.getElementById("name-input").value.trim()||"玩家";
  localStorage.removeItem("mahjong_session");
  send({t:"create", name, game_type:gameType});
};
document.getElementById("btn-join").onclick=()=>{
  const name=document.getElementById("name-input").value.trim()||"玩家";
  const code=document.getElementById("code-input").value.trim().toUpperCase();
  if(code.length!==4){ flashError("請輸入 4 碼房間代碼"); return; }
  localStorage.removeItem("mahjong_session");
  send({t:"join", code, name});
};
document.getElementById("btn-copy").onclick=()=>{
  navigator.clipboard?.writeText(roomCode);
  const b=document.getElementById("btn-copy"); const o=b.textContent;
  b.textContent="已複製！"; setTimeout(()=>b.textContent=o,1500);
};
document.getElementById("btn-start").onclick=()=> send({t:"start"});

// 離開房間 / 離開牌局 / 重開牌局
function doLeave(msg){
  if(!confirm(msg)) return;
  send({t:"leave"});
  // 保險：伺服器沒回應也讓自己回大廳
  setTimeout(()=>{ if(!document.getElementById("lobby").classList.contains("active")) backToLobby(); }, 1200);
}
function backToLobby(){
  localStorage.removeItem("mahjong_session");
  mySeat=null; roomCode=null; token=null; hostSeat=0;
  lastPublic=null; lastPrivate=null; sfxPrev=null; curHandNo=null;
  document.getElementById("result-overlay").classList.remove("show");
  show("lobby");
}
document.getElementById("btn-leave-room").onclick=()=> doLeave("確定離開這個房間？");
document.getElementById("btn-leave-game").onclick=()=> doLeave("確定退出牌局回大廳？本局會中止。");
document.getElementById("btn-restart").onclick=()=>{
  if(mySeat!==hostSeat){ flashError("只有房主可以重開牌局"); return; }
  if(confirm("重新洗牌發牌？本局作廢，分數保留。")) send({t:"restart"});
};

// 全螢幕（Android Chrome / iPad Safari 支援；iPhone Safari 無此 API，需「加到主畫面」）
const fsBtn=document.getElementById("btn-fs");
const fsSupported = !!(document.documentElement.requestFullscreen ||
                       document.documentElement.webkitRequestFullscreen);
const inStandalone = window.matchMedia("(display-mode: standalone)").matches ||
                     window.matchMedia("(display-mode: fullscreen)").matches ||
                     window.navigator.standalone === true;
if(!fsSupported || inStandalone){
  fsBtn.style.display="none";           // 不支援或已是 App 模式就不顯示
}
fsBtn.onclick=()=>{
  const el=document.documentElement;
  const isFs = document.fullscreenElement || document.webkitFullscreenElement;
  try{
    if(isFs){ (document.exitFullscreen||document.webkitExitFullscreen).call(document); }
    else { (el.requestFullscreen||el.webkitRequestFullscreen).call(el); }
  }catch(e){}
};
document.addEventListener("fullscreenchange",()=>{
  fsBtn.textContent = document.fullscreenElement ? "⛶" : "⛶";
});

// ---- 語音聊天 ----
Voice.init({
  send,
  onUpdate: ()=>{ syncVoiceBtns(); paintSpeaking(); },
});
function syncVoiceBtns(){
  const label = !Voice.enabled ? "🎤 語音"
              : (Voice.muted ? "🔇 已閉麥" : "🎙 通話中");
  ["btn-voice","pk-voice"].forEach(id=>{
    const b=document.getElementById(id);
    if(!b) return;
    b.textContent=label;
    b.classList.toggle("voice-on", Voice.enabled && !Voice.muted);
    b.classList.toggle("voice-muted", Voice.enabled && Voice.muted);
  });
}
// 在名牌／座位卡上標出「誰正在講話」
function paintSpeaking(){
  document.querySelectorAll("[data-seat-mark]").forEach(el=>{
    const s=+el.getAttribute("data-seat-mark");
    el.classList.toggle("speaking", Voice.enabled && Voice.isSpeaking(s));
  });
}
setInterval(paintSpeaking, 200);

async function toggleVoice(){
  if(!Voice.supported){
    showNotice("這個瀏覽器不支援語音聊天");
    return;
  }
  if(!Voice.enabled){
    try{
      await Voice.enable();
      Voice.setSeat(mySeat);
      showNotice("語音已開啟，再按一次可閉麥");
    }catch(e){
      showNotice("無法使用麥克風：請允許權限（且需 https）");
      return;
    }
  }else{
    // 已開 → 第一次按閉麥，閉麥狀態再按就完全關閉
    if(!Voice.muted) Voice.toggleMute();
    else Voice.disable();
  }
  syncVoiceBtns();
}
["btn-voice","pk-voice"].forEach(id=>{
  const b=document.getElementById(id);
  if(b) b.onclick=toggleVoice;
});
syncVoiceBtns();

// 音效開關
const sndBtn=document.getElementById("btn-sound");
function syncSoundBtn(){ sndBtn.textContent = SFX.enabled ? "🔊" : "🔇"; }
sndBtn.onclick=()=>{ SFX.toggle(); syncSoundBtn(); };
syncSoundBtn();

function sendConfig(){
  send({t:"set_config",
    base: parseInt(document.getElementById("cfg-base").value)||0,
    tai_value: parseInt(document.getElementById("cfg-tai").value)||0,
    rounds_target: parseInt(document.getElementById("cfg-rounds").value)||1,
    dice_rule: document.getElementById("cfg-dice").checked,
    small_blind: parseInt(document.getElementById("cfg-sb").value)||10,
    big_blind: parseInt(document.getElementById("cfg-bb").value)||20,
    start_stack: parseInt(document.getElementById("cfg-stack").value)||1000,
    bounty_27: document.getElementById("cfg-bounty27").checked,
    turn_seconds: parseInt(document.getElementById("cfg-turn").value)});
}
["cfg-base","cfg-tai","cfg-rounds","cfg-dice","cfg-sb","cfg-bb","cfg-stack",
 "cfg-bounty27","cfg-turn"].forEach(id=>
  document.getElementById(id).addEventListener("change", sendConfig));

// 德州牌桌的離開／下一手／炸彈彩池／結算
document.getElementById("pk-leave").onclick=()=> doLeave("確定退出牌局回大廳？");
document.getElementById("pk-next").onclick=()=> send({t:"next"});
document.getElementById("pk-bomb").onclick=()=>{
  const ante=(lastPublic?.big_blind||20)*5;
  if(confirm(`下一手改打炸彈彩池？\n每家先下底注 ${ante}（5 個大盲），不打翻牌前，直接發翻牌。`))
    send({t:"next", bomb_pot:true});
};
document.getElementById("pk-settle").onclick=()=> showSettlement();
document.getElementById("pk-settle-close").onclick=()=>
  document.getElementById("pk-settle-panel").classList.remove("show");

// 遊戲結算面板
function showSettlement(){
  const rows=lastPublic?.settlement||[];
  const tbl=document.getElementById("pk-settle-table");
  tbl.innerHTML="<tr class='hd'><td>玩家</td><td>買入</td><td>目前</td><td>淨輸贏</td></tr>";
  rows.forEach((r,i)=>{
    const tr=document.createElement("tr");
    const medal=["🥇","🥈","🥉"][i]||"";
    tr.innerHTML=`<td>${medal} ${escapeHtml(r.name)}${r.seat===mySeat?"（你）":""}`+
      `${r.rebuy?`<small> 補${r.rebuy}</small>`:""}</td>`+
      `<td>${r.buyin.toLocaleString()}</td>`+
      `<td>${r.stack.toLocaleString()}</td>`+
      `<td class="${r.net>=0?'pos':'neg'}">${r.net>=0?'+':''}${r.net.toLocaleString()}</td>`;
    tbl.appendChild(tr);
  });
  document.getElementById("pk-settle-panel").classList.add("show");
}
document.getElementById("btn-next").onclick=()=>{
  send({t:"next"});
  document.getElementById("result-overlay").classList.remove("show");
};

// ---- 等待室 ----
function renderWaiting(m){
  if(m.game_type) setGameType(m.game_type);
  const ul=document.getElementById("seat-list"); ul.innerHTML="";
  const minPlayers=m.min_players||4;
  let filled=0;
  m.players.forEach((p,i)=>{
    const li=document.createElement("li");
    if(p){
      filled++;
      li.innerHTML=`<span>${escapeHtml(p.name)} ${i===mySeat?"（你）":""}</span>`;
      const wrap=document.createElement("span");
      if(i===m.host_seat){ const b=document.createElement("span"); b.className="badge"; b.textContent="房主"; wrap.appendChild(b); }
      if(!p.connected){ const s=document.createElement("span"); s.textContent=" 離線"; s.style.opacity=.5; wrap.appendChild(s); }
      li.appendChild(wrap);
    }else{
      li.className="empty"; li.textContent=`座位 ${i+1}　等待加入…`;
    }
    ul.appendChild(li);
  });
  const isHost = mySeat===m.host_seat;
  // 底/台/骰規設定
  const cfg = m.config||{};
  document.getElementById("cfg-base").value = cfg.base ?? 100;
  document.getElementById("cfg-tai").value = cfg.tai_value ?? 20;
  document.getElementById("cfg-rounds").value = String(cfg.rounds_target ?? 1);
  document.getElementById("cfg-dice").checked = !!cfg.dice_rule;
  // 德州設定
  document.getElementById("cfg-sb").value = cfg.small_blind ?? 10;
  document.getElementById("cfg-bb").value = cfg.big_blind ?? 20;
  document.getElementById("cfg-stack").value = cfg.start_stack ?? 1000;
  document.getElementById("cfg-bounty27").checked = cfg.bounty_27 !== false;
  document.getElementById("cfg-turn").value = String(cfg.turn_seconds ?? 20);
  ["cfg-base","cfg-tai","cfg-rounds","cfg-dice",
   "cfg-sb","cfg-bb","cfg-stack","cfg-bounty27","cfg-turn"].forEach(id=>
    document.getElementById(id).disabled = !isHost);
  document.getElementById("cfg-hint").textContent =
    isHost ? "（房主可調整；開局後鎖定）" : "由房主設定";

  const startBtn=document.getElementById("btn-start");
  startBtn.style.display = isHost ? "block":"none";
  startBtn.disabled = filled<minPlayers;
  document.getElementById("wait-hint").textContent =
    filled<minPlayers ? `目前 ${filled} 人，還需 ${minPlayers-filled} 人才能開始` :
    (isHost? `人數 ${filled}/${m.max_seats||4}，可以開始！` : "等待房主開始…");
  if(m.started){ /* 已開局，等 state 訊息 */ }
}

// ---- 牌桌 ----
function relPos(seat){
  const d=(seat-mySeat+4)%4;
  return ["bottom","right","top","left"][d];
}
function renderTable(){
  const pub=lastPublic, pri=lastPrivate;
  // 資訊列
  const pg=pub.progress;
  document.getElementById("info-round").textContent =
    pg ? `${WIND_CN[pg.round_wind]}圈 ${pg.round_index+1}/${pg.rounds_target}`
       : `${WIND_CN[pub.round_wind]}圈`;
  document.getElementById("info-wall").textContent=`剩 ${pub.wall_left} 張`;
  const turnName = pub.players[pub.turn]?.name||"";
  document.getElementById("info-turn").textContent=
    pub.phase==="over" ? "本局結束" : `輪到 ${turnName}`;
  // 輪到誰：整個牌桌加提示（輪到自己時邊框發光 + 橫幅）
  const board=document.getElementById("board");
  const myTurn = pub.phase!=="over" &&
    ((pub.phase==="await_discard" && pub.turn===mySeat) ||
     (pub.phase==="await_reaction" && (pri.reactions||[]).length>0));
  board.classList.toggle("my-turn", myTurn);
  let banner=document.getElementById("turn-banner");
  if(!banner){
    banner=document.createElement("div"); banner.id="turn-banner";
    board.appendChild(banner);
  }
  banner.innerHTML = (pub.phase==="await_reaction" && (pri.reactions||[]).length)
    ? "換你決定！" : "輪到你出牌";
  if(myTurn) banner.appendChild(timerEl());   // 自己的倒數放在橫幅上
  banner.classList.toggle("show", myTurn);
  // 標出目前輪到的那一家（座位區整塊發光）。
  // 反應階段不標任何人 —— 那時 turn 還停在剛打牌的人身上，
  // 若繼續發光等於告訴大家「有人正在考慮吃碰胡」。
  const showTurnMark = (pub.phase==="await_discard");
  ["top","left","right","bottom"].forEach(p=>{
    const el=document.querySelector(`.seat-area.${p}`);
    if(el) el.classList.toggle("is-turn", showTurnMark && relPos(pub.turn)===p);
  });

  // 輪到誰的指向箭頭（指向當前出牌者）
  const ptr=document.getElementById("turn-pointer");
  if(!showTurnMark){
    // 結束或反應階段都不指 —— 反應階段還指著剛打牌的人會洩漏「有人在考慮」
    ptr.style.display="none";
  }else{
    const rot={bottom:180, right:90, top:0, left:270}[relPos(pub.turn)];
    ptr.style.display="";
    // 旋轉指向該家，並往那個方向外推，避免壓在牌河上
    ptr.style.transform=`translate(-50%,-50%) rotate(${rot}deg) translateY(-74px)`;
    ptr.classList.toggle("mine", pub.turn===mySeat);
  }
  // 只有房主看得到「重開」
  document.getElementById("btn-restart").style.display =
    (mySeat===hostSeat) ? "" : "none";
  // 骰規骰子
  const diceEl=document.getElementById("info-dice");
  if(pub.dice){
    const pat = pub.dice.patterns.length? " "+pub.dice.patterns.join("+") : "";
    diceEl.textContent = `🎲 ${pub.dice.values.join("·")}${pat}`;
    diceEl.style.display="";
  }else{
    diceEl.style.display="none";
  }

  // 清空
  ["top","left","right"].forEach(p=>document.querySelector(`.seat-area.${p}`).innerHTML="");
  document.getElementById("my-melds").innerHTML="";
  document.getElementById("my-hand").innerHTML="";
  document.getElementById("center-pool").innerHTML="";

  // 對手三家
  pub.players.forEach(pl=>{
    if(pl.seat===mySeat) return;
    renderOpponent(pl, relPos(pl.seat), pub);
  });
  // 中央棄牌河
  renderPool(pub);
  // 自己
  renderMe(pub, pri);
  // 牌河定位要在所有座位都畫完之後（要量到含亮牌/手牌的真實範圍）
  layoutRivers();
  updateTimerUI();     // 重繪會重建倒數元件，立刻填值才不會閃一下空白
  // 動作列
  renderActions(pub, pri);
  // 結算
  if(pub.phase==="over"){ renderResult(pub); }
  else { document.getElementById("result-overlay").classList.remove("show"); }
}

function nameplate(pl, pub){
  const np=document.createElement("div");
  const isTurn = pub.turn===pl.seat && pub.phase!=="over";
  np.className="nameplate"+(isTurn?" active-turn":"");
  const wind = pl.wind? `<span class="wind">${WIND_CN[pl.wind]}</span>`:"";
  const dealer = pl.seat===pub.dealer ? "🀄":"";
  // 斷線／暫離要讓其他人看得到，才知道在等誰
  const off = (pub.connected && pub.connected[pl.seat]===false)
    ? '<span class="tag-off">斷線</span>' : "";
  const afk = (pub.afk && pub.afk[pl.seat]) ? '<span class="tag-afk">暫離</span>' : "";
  np.setAttribute("data-seat-mark", pl.seat);   // 給語音「誰在講話」用
  np.innerHTML=`${wind}${escapeHtml(pl.name)}${dealer}`+
               `<span class="sc">${pl.score}</span>${off}${afk}`;
  if(isTurn) np.appendChild(timerEl());   // 輪到他 → 名牌上顯示倒數
  return np;
}

function renderOpponent(pl, pos, pub){
  const area=document.querySelector(`.seat-area.${pos}`);
  const side = (pos==="left"||pos==="right");
  const rot  = side ? "rot" : "";        // 左右家的牌轉 90 度
  area.appendChild(nameplate(pl, pub));

  // 手牌背面
  const backs=document.createElement("div"); backs.className="hand-backs";
  for(let i=0;i<pl.hand_count;i++) backs.appendChild(tileEl("we","back small "+rot));

  // 亮牌 + 花
  const melds=document.createElement("div"); melds.className="melds";
  pl.melds.forEach(md=> melds.appendChild(meldGroup(md, rot)));
  if(pl.flowers.length){
    const fg=document.createElement("div"); fg.className="meld-group";
    pl.flowers.forEach(f=> fg.appendChild(tileEl(f,"small "+rot)));
    melds.appendChild(fg);
  }

  if(side){
    // 左右家：亮牌擺在手牌「前面」（靠牌桌中央那側）
    const rowEl=document.createElement("div");
    rowEl.className="side-row "+pos;
    rowEl.append(backs, melds);
    area.appendChild(rowEl);
  }else{
    area.append(backs, melds);
  }
}

// 吃的牌擺法：手上兩張維持順序，吃來的那張放中間（例：1筒2筒 吃 3筒 → 1筒 3筒 2筒）
function meldTileOrder(md){
  if(md.kind==="ankong") return [md.tiles[0],"back","back",md.tiles[0]];
  if(md.kind==="chow" && md.claimed){
    const others=[...md.tiles];
    const i=others.indexOf(md.claimed);
    if(i>=0){
      others.splice(i,1);                    // 去掉吃來的那張
      return [others[0], md.claimed, others[1]];
    }
  }
  return md.tiles;
}

function meldGroup(md, cls=""){
  const g=document.createElement("div"); g.className="meld-group";
  meldTileOrder(md).forEach(c=>{
    if(c==="back") g.appendChild(tileEl("we","back small "+cls));
    else g.appendChild(tileEl(c,"small "+cls));
  });
  return g;
}

// 牌河定位：依「實際量到的座位範圍」把牌河貼在該家外側，
// 不用寫死百分比 —— 座位會因為吃碰槓與花牌而變寬，寫死就會互相遮擋。
function layoutRivers(){
  const board=document.getElementById("board");
  if(!board) return;
  const br=board.getBoundingClientRect();
  const GAP=8;
  const seatRect=(p)=>{
    const e=document.querySelector(`.seat-area.${p}`);
    return e ? e.getBoundingClientRect() : null;
  };
  const set=(pos, styles)=>{
    const el=document.querySelector(`.river-box.${pos}`);
    if(el) Object.assign(el.style, styles);
  };
  const t=seatRect("top"), b=seatRect("bottom"),
        l=seatRect("left"), r=seatRect("right");
  // 上下：貼在座位內側（靠桌中央那一邊）
  if(t) set("top",    {top:(t.bottom-br.top+GAP)+"px", bottom:"auto"});
  if(b) set("bottom", {bottom:(br.bottom-b.top+GAP)+"px", top:"auto"});
  // 左右：貼在座位內側，並限制寬度避免壓到中央
  if(l) set("left",   {left:(l.right-br.left+GAP)+"px", right:"auto"});
  if(r) set("right",  {right:(br.right-r.left+GAP)+"px", left:"auto"});
}

// 每個人打出的牌，就擺在「那個人前面」（自己與桌子中央之間）
function renderPool(pub){
  const pool=document.getElementById("center-pool");
  const lastCode = pub.last_discard? pub.last_discard[1]:null;
  const lastSeat = pub.last_discard? pub.last_discard[0]:null;
  pub.players.forEach(pl=>{
    const pos=relPos(pl.seat);
    const box=document.createElement("div");
    box.className="river-box "+pos+(pub.turn===pl.seat?" active":"");
    const river=document.createElement("div"); river.className="discards";
    pl.discards.forEach((c,idx)=>{
      const isLast = pl.seat===lastSeat && idx===pl.discards.length-1;
      river.appendChild(tileEl(c,"mini"+(isLast?" last-tile just-discarded":"")));
    });
    box.appendChild(river);
    pool.appendChild(box);
  });
  // 「剛打出哪張」放到上方資訊列，中央整塊留給四家的牌河，才不會互相擋
  const info=document.getElementById("info-last");
  if(info){
    if(lastCode){
      info.innerHTML="";
      const who=document.createElement("span");
      who.textContent=(pub.players[lastSeat]?.name||"")+" 打出";
      info.append(who, tileEl(lastCode,"mini last-tile"));
      info.style.display="";
    }else{
      info.style.display="none";
    }
  }
}

function renderMe(pub, pri){
  const me=pub.players[mySeat];
  const area=document.querySelector(".seat-area.bottom");
  // 名牌放在手牌上方（用 info-turn 已示意，這裡加亮牌）
  const meldBox=document.getElementById("my-melds");
  me.melds.forEach(md=> meldBox.appendChild(meldGroup(md)));
  if(me.flowers.length){
    const fg=document.createElement("div"); fg.className="meld-group";
    me.flowers.forEach(f=> fg.appendChild(tileEl(f,"small")));
    meldBox.appendChild(fg);
  }
  // 手牌（可點擊出牌）
  const handBox=document.getElementById("my-hand");
  const canDiscard = pub.phase==="await_discard" && pub.turn===mySeat;
  // 剛摸到的那張獨立擺到最右邊，不排進手牌裡
  const rest=[...(pri.hand||[])];
  let drawn=null;
  if(pri.drawn){
    const i=rest.indexOf(pri.drawn);
    if(i>=0){ rest.splice(i,1); drawn=pri.drawn; }
  }
  const addTile=(c,extra)=>{
    const t=tileEl(c, extra||"");
    if(canDiscard){
      t.onclick=()=> send({t:"discard", tile:c});
      t.title="點擊打出 "+tileName(c);
    }else{
      t.style.cursor="default";
    }
    handBox.appendChild(t);
  };
  rest.forEach(c=> addTile(c));
  if(drawn) addTile(drawn, "just-drawn");
}

function renderActions(pub, pri){
  const bar=document.getElementById("action-bar"); bar.innerHTML="";
  if(pub.phase==="over") return;

  // 自己回合的特殊動作
  if(pub.phase==="await_discard" && pub.turn===mySeat){
    const so=pri.self_options||{};
    if(so.tsumo) addBtn(bar,"自摸 🀄","act-self",()=>send({t:"self",action:"tsumo"}));
    (so.ankong||[]).forEach(tl=>
      addBtn(bar,`暗槓 ${tileName(tl)}`,"act-self",()=>send({t:"self",action:"ankong",tile:tl})));
    (so.addkong||[]).forEach(tl=>
      addBtn(bar,`加槓 ${tileName(tl)}`,"act-self",()=>send({t:"self",action:"addkong",tile:tl})));
    return;
  }

  // 別人打牌後的反應
  if(pub.phase==="await_reaction" && pri.reactions && pri.reactions.length){
    const acts=pri.reactions;
    if(acts.includes("hu"))
      addBtn(bar,"胡","act-big act-hu",()=>send({t:"claim",action:"hu"}));
    if(acts.includes("kong"))
      addBtn(bar,"槓","act-big act-kong", ()=>send({t:"claim",action:"kong"}));
    if(acts.includes("pong"))
      addBtn(bar,"碰","act-big act-pong", ()=>send({t:"claim",action:"pong"}));
    if(acts.includes("chow"))
      addChow(bar, pri);
    addBtn(bar,"過","act-pass",()=>send({t:"claim",action:"pass"}));
  }
}

function addBtn(bar,label,cls,fn){
  const b=document.createElement("button"); b.textContent=label;
  if(cls) b.className=cls; b.onclick=fn; bar.appendChild(b);
}

function addChow(bar, pri){
  const opts=pri.chow_options||[];
  if(opts.length<=1){
    addBtn(bar,"吃","act-big act-chow",()=>send({t:"claim",action:"chow",tiles:opts[0]||null}));
  }else{
    // 多組吃法：每組一顆按鈕
    opts.forEach(pair=>{
      const label="吃 "+pair.map(tileName).join("");
      addBtn(bar,label,"act-big act-chow",()=>send({t:"claim",action:"chow",tiles:pair}));
    });
  }
}

// 結算時亮出贏家整副牌
function revealHand(rev, winTile){
  const box=document.createElement("div"); box.className="reveal";
  const lbl=document.createElement("div"); lbl.className="reveal-label";
  lbl.textContent="胡牌牌型";
  box.appendChild(lbl);

  const row=document.createElement("div"); row.className="reveal-row";
  // 手牌（胡的那張標出來，只標一張）
  let marked=false;
  (rev.hand||[]).forEach(c=>{
    const t=tileEl(c,"rv");
    if(!marked && c===winTile){ t.classList.add("win-tile"); marked=true; }
    row.appendChild(t);
  });
  // 亮出的面子
  (rev.melds||[]).forEach(md=>{
    const g=document.createElement("div"); g.className="reveal-meld";
    meldTileOrder(md).forEach(c=> g.appendChild(
      tileEl(c==="back"?"we":c, c==="back"?"rv back":"rv")));
    row.appendChild(g);
  });
  box.appendChild(row);

  // 花
  if((rev.flowers||[]).length){
    const fr=document.createElement("div"); fr.className="reveal-row reveal-flowers";
    rev.flowers.forEach(f=> fr.appendChild(tileEl(f,"rv")));
    box.appendChild(fr);
  }
  return box;
}

function renderResult(pub){
  const r=pub.result; if(!r) return;
  const ov=document.getElementById("result-overlay");
  const title=document.getElementById("result-title");
  const detail=document.getElementById("result-detail");
  detail.innerHTML="";
  if(r.type==="draw"){
    title.textContent="流局";
    detail.innerHTML="<p>牌牆摸完，無人胡牌，莊家連莊。</p>";
  }else{
    const winners = r.winners || [{seat:r.winner, tai:r.tai, tai_detail:r.tai_detail,
                                   reveal:r.reveal, settle:{amount:r.settle?.amount,
                                   eff_tai:r.settle?.eff_tai}}];
    const names = winners.map(w=>pub.players[w.seat]?.name||"").join("、");
    const MULTI={2:"一炮雙響",3:"一炮三響"};
    title.textContent = winners.length>1
      ? `${MULTI[winners.length]||"一炮多響"}！${names} 胡牌`
      : `${names} 胡牌！`;
    const st=r.settle;
    const way = r.self_draw? "自摸" : `胡 ${pub.players[r.discarder]?.name||""} 打出的牌`;
    let html=`<p>${way}　<b>${tileName(r.win_tile)}</b></p>`;
    if(st){
      html+=`<p class="settle">底 ${st.base}｜每台 ${st.tai_value}`;
      if(st.dice){
        html+=`｜🎲 ${st.dice.values.join("·")}`;
        if(st.dice.patterns.length) html+=` ${st.dice.patterns.join("+")}`;
      }
      html+=`</p>`;
    }
    detail.innerHTML=html;
    const dbl = st && st.dice && st.dice.double ? "（豹子翻倍）" : "";
    // 每位贏家各自一段：台數明細 + 亮牌
    winners.forEach(w=>{
      const sec=document.createElement("div"); sec.className="winner-sec";
      if(winners.length>1){
        const h=document.createElement("div"); h.className="winner-name";
        h.textContent=`${pub.players[w.seat]?.name||""}　${w.tai} 台`;
        sec.appendChild(h);
      }
      let inner="";
      (w.tai_detail||[]).forEach(([nm,t])=>{
        inner+=`<div class="tai-row"><span>${nm}</span><span>${t>0?"+"+t:t} 台</span></div>`;
      });
      const ws=w.settle;
      if(ws && ws.amount!=null){
        inner+=`<p class="settle">共 <b>${ws.eff_tai}</b> 台${dbl} → 收 <b>${ws.amount}</b> 分</p>`;
      }
      const body=document.createElement("div"); body.innerHTML=inner;
      sec.appendChild(body);
      if(w.reveal) sec.appendChild(revealHand(w.reveal, r.win_tile));
      detail.appendChild(sec);
    });
    if(winners.length>1 && st && st.total_paid!=null){
      const tp=document.createElement("p"); tp.className="settle total-paid";
      tp.innerHTML=`${pub.players[r.discarder]?.name||"放槍者"} 共付 <b>${st.total_paid}</b> 分`;
      detail.appendChild(tp);
    }
  }
  // 分數表
  const tbl=document.getElementById("score-table"); tbl.innerHTML="";
  pub.players.forEach(p=>{
    const tr=document.createElement("tr");
    const sc=p.score;
    tr.innerHTML=`<td>${escapeHtml(p.name)}${p.seat===mySeat?"（你）":""}</td>`+
      `<td class="${sc>=0?'pos':'neg'}">${sc>=0?'+':''}${sc}</td>`;
    tbl.appendChild(tr);
  });
  // 整場結束 → 顯示最終排名
  const done = pub.progress && pub.progress.finished;
  if(done && pub.standings){
    const fin=document.createElement("div"); fin.className="final-box";
    const rt=pub.progress.rounds_target;
    fin.innerHTML=`<div class="final-title">🏆 ${rt===4?"一將":rt+"圈"}打完　最終排名</div>`;
    const ol=document.createElement("ol"); ol.className="final-rank";
    pub.standings.forEach((s,i)=>{
      const li=document.createElement("li");
      li.innerHTML=`<span>${["🥇","🥈","🥉","4."][i]||""} ${escapeHtml(s.name)}`+
        `${s.seat===mySeat?"（你）":""}</span>`+
        `<span class="${s.score>=0?'pos':'neg'}">${s.score>=0?'+':''}${s.score}</span>`;
      ol.appendChild(li);
    });
    fin.appendChild(ol);
    detail.appendChild(fin);
  }

  // 只有房主能開下一局（房主可能因原房主離開而換人）
  const isHost = mySeat===hostSeat;
  const nextBtn=document.getElementById("btn-next");
  nextBtn.style.display = isHost?"block":"none";
  nextBtn.textContent = done ? "再開一場" : "下一局";
  if(done && isHost) nextBtn.onclick=()=>{ send({t:"restart"}); ov.classList.remove("show"); };
  else if(isHost) nextBtn.onclick=()=>{ send({t:"next"}); ov.classList.remove("show"); };
  document.getElementById("next-hint").textContent =
    isHost? "" : (done? "等待房主開新的一場…" : "等待房主開下一局…");
  ov.classList.add("show");
}

function escapeHtml(s){ return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// 測試掛鉤（除錯用，不影響正常遊戲）
window.__mj = { handle, get state(){ return {lastPublic, lastPrivate, mySeat}; } };

// 啟動
connect();
