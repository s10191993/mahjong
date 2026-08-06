"use strict";
// 牌面繪製（tileEl / tileName / 配色）已抽到 tiles.js，index.html 先載入它。

// ---- 狀態 ----
let ws=null, mySeat=null, roomCode=null, token=null;
let lastPublic=null, lastPrivate=null;
// 音效用：記住上一次的牌局狀態，用來偵測「發生了什麼事」
let sfxPrev=null, curHandNo=null;

// 比較新舊狀態，播對應音效
function playStateSounds(pub, pri){
  const prev=sfxPrev;
  const snap={
    handNo: null,
    discards: pub.players.map(p=>p.discards.length),
    melds: pub.players.map(p=>p.melds.length),
    meldKinds: pub.players.map(p=>p.melds.map(m=>m.kind).join(",")),
    flowers: pub.players.map(p=>p.flowers.length),
    phase: pub.phase, turn: pub.turn,
    over: pub.phase==="over",
  };
  if(prev){
    // 有人吃/碰/槓（亮牌數變多）
    for(let i=0;i<4;i++){
      if(snap.melds[i] > prev.melds[i]){
        const kinds=pub.players[i].melds;
        const k=kinds[kinds.length-1]?.kind;
        SFX.play(k==="chow"?"chow": (k==="pong"?"pong":"kong"));
      }else if(snap.meldKinds[i]!==prev.meldKinds[i]){
        SFX.play("kong");            // 碰→加槓（組數沒變但類型變了）
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
      localStorage.setItem("mahjong_session", JSON.stringify({code:roomCode, token}));
      document.getElementById("room-code").textContent=roomCode;
      show("waiting");
      break;
    case "room":
      renderWaiting(m);
      break;
    case "state":
      if(m.hand_no!==undefined && m.hand_no!==curHandNo){ curHandNo=m.hand_no; sfxPrev=null; }
      lastPublic=m.public; lastPrivate=m.private;
      show("table");
      renderTable();
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
document.getElementById("btn-create").onclick=()=>{
  const name=document.getElementById("name-input").value.trim()||"玩家";
  localStorage.removeItem("mahjong_session");
  send({t:"create", name});
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

// 音效開關
const sndBtn=document.getElementById("btn-sound");
function syncSoundBtn(){ sndBtn.textContent = SFX.enabled ? "🔊" : "🔇"; }
sndBtn.onclick=()=>{ SFX.toggle(); syncSoundBtn(); };
syncSoundBtn();

function sendConfig(){
  send({t:"set_config",
    base: parseInt(document.getElementById("cfg-base").value)||0,
    tai_value: parseInt(document.getElementById("cfg-tai").value)||0,
    dice_rule: document.getElementById("cfg-dice").checked});
}
["cfg-base","cfg-tai","cfg-dice"].forEach(id=>
  document.getElementById(id).addEventListener("change", sendConfig));
document.getElementById("btn-next").onclick=()=>{
  send({t:"next"});
  document.getElementById("result-overlay").classList.remove("show");
};

// ---- 等待室 ----
function renderWaiting(m){
  const ul=document.getElementById("seat-list"); ul.innerHTML="";
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
  document.getElementById("cfg-dice").checked = !!cfg.dice_rule;
  ["cfg-base","cfg-tai","cfg-dice"].forEach(id=>
    document.getElementById(id).disabled = !isHost);
  document.getElementById("cfg-hint").textContent =
    isHost ? "（房主可調整；開局後鎖定）" : "由房主設定";

  const startBtn=document.getElementById("btn-start");
  startBtn.style.display = isHost ? "block":"none";
  startBtn.disabled = filled<4;
  document.getElementById("wait-hint").textContent =
    filled<4 ? `目前 ${filled}/4 人，還需 ${4-filled} 人` :
    (isHost? "人齊了，按開始！" : "等待房主開始…");
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
  document.getElementById("info-round").textContent=`${WIND_CN[pub.round_wind]}圈`;
  document.getElementById("info-wall").textContent=`剩 ${pub.wall_left} 張`;
  const turnName = pub.players[pub.turn]?.name||"";
  document.getElementById("info-turn").textContent=
    pub.phase==="over" ? "本局結束" : `輪到 ${turnName}`;
  // 輪到誰的指向箭頭（指向當前出牌者）
  const ptr=document.getElementById("turn-pointer");
  if(pub.phase==="over"){
    ptr.style.display="none";
  }else{
    const rot={bottom:180, right:90, top:0, left:270}[relPos(pub.turn)];
    ptr.style.display="";
    // 旋轉指向該家，並往那個方向外推，避免壓在牌河上
    ptr.style.transform=`translate(-50%,-50%) rotate(${rot}deg) translateY(-74px)`;
    ptr.classList.toggle("mine", pub.turn===mySeat);
  }
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
  // 動作列
  renderActions(pub, pri);
  // 結算
  if(pub.phase==="over"){ renderResult(pub); }
  else { document.getElementById("result-overlay").classList.remove("show"); }
}

function nameplate(pl, pub){
  const np=document.createElement("div");
  np.className="nameplate"+(pub.turn===pl.seat && pub.phase!=="over"?" active-turn":"");
  const wind = pl.wind? `<span class="wind">${WIND_CN[pl.wind]}</span>`:"";
  const dealer = pl.seat===pub.dealer ? "🀄":"";
  np.innerHTML=`${wind}${escapeHtml(pl.name)}${dealer}<span class="sc">${pl.score}</span>`;
  return np;
}

function renderOpponent(pl, pos, pub){
  const area=document.querySelector(`.seat-area.${pos}`);
  area.appendChild(nameplate(pl, pub));
  // 手牌背面
  const backs=document.createElement("div"); backs.className="hand-backs";
  for(let i=0;i<pl.hand_count;i++) backs.appendChild(tileEl("we","back small"));
  area.appendChild(backs);
  // 亮牌 + 花
  const melds=document.createElement("div"); melds.className="melds";
  pl.melds.forEach(md=> melds.appendChild(meldGroup(md)));
  if(pl.flowers.length){
    const fg=document.createElement("div"); fg.className="meld-group";
    pl.flowers.forEach(f=> fg.appendChild(tileEl(f,"small")));
    melds.appendChild(fg);
  }
  area.appendChild(melds);
}

function meldGroup(md){
  const g=document.createElement("div"); g.className="meld-group";
  const codes = (md.kind==="ankong") ? [md.tiles[0],"back","back",md.tiles[0]] : md.tiles;
  codes.forEach(c=>{
    if(c==="back") g.appendChild(tileEl("we","back small"));
    else g.appendChild(tileEl(c,"small"));
  });
  return g;
}

function renderPool(pub){
  const pool=document.getElementById("center-pool");
  const posSlot={bottom:"s",right:"e",top:"n",left:"w"};
  const lastCode = pub.last_discard? pub.last_discard[1]:null;
  const lastSeat = pub.last_discard? pub.last_discard[0]:null;
  pub.players.forEach(pl=>{
    const slot=document.createElement("div");
    slot.className="slot "+posSlot[relPos(pl.seat)];
    const river=document.createElement("div"); river.className="discards";
    pl.discards.forEach((c,idx)=>{
      const isLast = pl.seat===lastSeat && idx===pl.discards.length-1;
      river.appendChild(tileEl(c,"mini"+(isLast?" last-tile":"")));
    });
    slot.appendChild(river);
    pool.appendChild(slot);
  });
  // 中央顯示最後一張打出的牌
  const c=document.createElement("div"); c.className="slot c";
  if(lastCode){
    const lbl=document.createElement("div"); lbl.className="pool-label"; lbl.textContent="最後一張";
    c.appendChild(lbl); c.appendChild(tileEl(lastCode,"last-tile"));
  }
  pool.appendChild(c);
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
  const hand = pri.hand||[];
  hand.forEach(c=>{
    const t=tileEl(c);
    if(canDiscard){
      t.onclick=()=> send({t:"discard", tile:c});
      t.title="點擊打出 "+tileName(c);
    }else{
      t.style.cursor="default";
    }
    handBox.appendChild(t);
  });
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
    const codes=(md.kind==="ankong")?[md.tiles[0],"back","back",md.tiles[0]]:md.tiles;
    codes.forEach(c=> g.appendChild(tileEl(c==="back"?"we":c, c==="back"?"rv back":"rv")));
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
  // 只有房主能開下一局
  const isHost = mySeat===0; // 房主固定座位0；伺服器會擋，非房主按了也沒用
  document.getElementById("btn-next").style.display = isHost?"block":"none";
  document.getElementById("next-hint").textContent = isHost? "" : "等待房主開下一局…";
  ov.classList.add("show");
}

function escapeHtml(s){ return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// 測試掛鉤（除錯用，不影響正常遊戲）
window.__mj = { handle, get state(){ return {lastPublic, lastPrivate, mySeat}; } };

// 啟動
connect();
