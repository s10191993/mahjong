"use strict";
// ============================================================
//  德州撲克牌桌 UI（由 client.js 在 game_type==="poker" 時呼叫）
// ============================================================
const SUIT_SYM = {s:"♠", h:"♥", d:"♦", c:"♣"};
const SUIT_RED = {h:true, d:true};
const PHASE_CN = {waiting:"等待中", preflop:"翻牌前", flop:"翻牌", turn:"轉牌",
                  river:"河牌", showdown:"攤牌", over:"本手結束"};

// 撲克牌面（背面傳 null）
function cardEl(code, cls=""){
  const d=document.createElement("div");
  d.className="pcard "+cls;
  if(!code){ d.classList.add("back"); return d; }
  const r=code[0]==="T" ? "10" : code[0];
  const s=code[1];
  d.classList.add(SUIT_RED[s] ? "red" : "black");
  d.innerHTML=`<span class="pc-r">${r}</span><span class="pc-s">${SUIT_SYM[s]}</span>`;
  d.dataset.code=code;
  return d;
}

function money(n){ return (n||0).toLocaleString("en-US"); }

// 依「我」的座位把其他人排在桌子周圍
function seatPositions(mySeat, seats){
  // seats: 有人的座位號陣列（含我）；回傳 seat -> {x%, y%}
  const others=seats.filter(s=>s!==mySeat);
  const n=others.length;
  const pos={};
  // 以橢圓分布，從左下逆時針排到右下（我在正下方）
  for(let i=0;i<n;i++){
    const t = Math.PI*(0.82 + (i+1)*(1.36/(n+1)));   // 避開正下方
    pos[others[i]]={x:50+41*Math.cos(t), y:47-38*Math.sin(t)};
  }
  return pos;
}

function renderPoker(pub, pri, mySeat){
  const seated=pub.players.filter(p=>p.name).map(p=>p.seat);
  document.getElementById("pk-blinds").textContent=
    `盲注 ${money(pub.small_blind)}/${money(pub.big_blind)}`;
  document.getElementById("pk-handno").textContent=`第 ${pub.hand_no} 手`;
  document.getElementById("pk-phase").textContent=PHASE_CN[pub.phase]||pub.phase;

  // 底池
  document.getElementById("pk-pot").innerHTML =
    pub.pot>0 ? `底池 <b>${money(pub.pot)}</b>` : "";

  // 公牌
  const bc=document.getElementById("pk-board-cards"); bc.innerHTML="";
  (pub.board||[]).forEach(c=> bc.appendChild(cardEl(c)));
  for(let i=(pub.board||[]).length;i<5;i++){
    const ph=document.createElement("div"); ph.className="pcard slot"; bc.appendChild(ph);
  }

  // 其他玩家
  const box=document.getElementById("pk-seats"); box.innerHTML="";
  const pos=seatPositions(mySeat, seated);
  pub.players.forEach(p=>{
    if(!p.name || p.seat===mySeat) return;
    const el=document.createElement("div");
    el.className="pk-seat"+(p.folded?" folded":"")+(pub.to_act===p.seat?" acting":"");
    const pp=pos[p.seat]||{x:50,y:10};
    el.style.left=pp.x+"%"; el.style.top=pp.y+"%";
    const cards=p.has_cards
      ? `<div class="pk-mini">${'<div class="pcard back mini"></div>'.repeat(2)}</div>` : "";
    const shown=(pub.result&&pub.result.shown&&pub.result.shown[p.seat]);
    const showCards=shown
      ? `<div class="pk-mini">${shown.hole.map(c=>{
            const r=c[0]==="T"?"10":c[0];
            return `<div class="pcard mini ${SUIT_RED[c[1]]?'red':'black'}">`+
                   `<span class="pc-r">${r}</span><span class="pc-s">${SUIT_SYM[c[1]]}</span></div>`;
         }).join("")}</div>` : cards;
    el.innerHTML =
      `${showCards}`+
      `<div class="pk-name">${p.seat===pub.button?'<span class="btn-d">D</span>':''}`+
      `${escapeHtml(p.name)}</div>`+
      `<div class="pk-stack">${money(p.stack)}</div>`+
      (p.bet>0?`<div class="pk-bet">${money(p.bet)}</div>`:"")+
      (p.last_action?`<div class="pk-act">${p.last_action}</div>`:"")+
      (shown?`<div class="pk-desc">${shown.desc}</div>`:"");
    box.appendChild(el);
  });

  // 我自己
  const me=pub.players.find(p=>p.seat===mySeat);
  const hole=document.getElementById("pk-hole"); hole.innerHTML="";
  if(me){
    const info=document.createElement("div"); info.className="pk-me-info";
    info.innerHTML=`${mySeat===pub.button?'<span class="btn-d">D</span>':''}`+
      `<b>${escapeHtml(me.name)}</b> <span class="pk-stack">${money(me.stack)}</span>`+
      (me.bet>0?` <span class="pk-bet">下注 ${money(me.bet)}</span>`:"")+
      (me.last_action?` <span class="pk-act">${me.last_action}</span>`:"");
    hole.appendChild(info);
    const cw=document.createElement("div"); cw.className="pk-hole-cards";
    (pri.hole||[]).forEach(c=> cw.appendChild(cardEl(c, me.folded?"dim":"")));
    hole.appendChild(cw);
    const mine=pub.result&&pub.result.shown&&pub.result.shown[mySeat];
    if(mine){
      const d=document.createElement("div"); d.className="pk-desc mine";
      d.textContent=mine.desc; hole.appendChild(d);
    }
  }

  // 結果訊息
  const msg=document.getElementById("pk-msg");
  if(pub.phase==="over" && pub.result){
    const r=pub.result;
    const names=(r.winners||[]).map(s=>pub.players.find(p=>p.seat===s)?.name||"").join("、");
    const amt=Object.values(r.payouts||{}).reduce((a,b)=>a+b,0);
    msg.innerHTML=`<b>${escapeHtml(names)}</b> 贏得 <b>${money(amt)}</b>`+
      (r.type==="fold_win"?"（其他人都蓋牌）":"");
    msg.classList.add("show");
  }else{
    msg.classList.remove("show"); msg.innerHTML="";
  }

  renderPokerActions(pub, pri, mySeat);
}

function renderPokerActions(pub, pri, mySeat){
  const bar=document.getElementById("pk-actions"); bar.innerHTML="";
  const nextBtn=document.getElementById("pk-next");
  nextBtn.style.display = (pub.phase==="over") ? "" : "none";
  const acts=pri.actions||{};
  if(!Object.keys(acts).length) return;

  const add=(label,cls,fn)=>{
    const b=document.createElement("button"); b.textContent=label;
    b.className="pk-btn "+(cls||""); b.onclick=fn; bar.appendChild(b);
  };
  if(acts.fold) add("蓋牌","pk-fold",()=>pokerAct("fold"));
  if(acts.check) add("過牌","pk-check",()=>pokerAct("check"));
  if(acts.call!==undefined) add(`跟注 ${money(acts.call)}`,"pk-call",()=>pokerAct("call"));

  if(acts.raise){
    const r=acts.raise;
    if(r.is_allin_only){
      add(`全下 ${money(r.max)}`,"pk-allin",()=>pokerAct("allin"));
    }else{
      // 加注：滑桿 + 快捷
      const wrap=document.createElement("div"); wrap.className="pk-raise";
      const val=document.createElement("div"); val.className="pk-raise-val";
      const rng=document.createElement("input");
      rng.type="range"; rng.min=r.min; rng.max=r.max; rng.step=1; rng.value=r.min;
      const sync=()=> val.textContent=`加注到 ${money(rng.value)}`;
      rng.oninput=sync; sync();
      const quick=document.createElement("div"); quick.className="pk-quick";
      const pot=pub.pot;
      [["½池",Math.round(pot/2)],["池",pot],["最小",r.min]].forEach(([lb,amt])=>{
        const target=Math.max(r.min, Math.min(r.max, Math.max(amt, r.min)));
        const b=document.createElement("button"); b.textContent=lb;
        b.className="pk-mini-btn";
        b.onclick=()=>{ rng.value=target; sync(); };
        quick.appendChild(b);
      });
      wrap.append(val, rng, quick);
      bar.appendChild(wrap);
      add("加注","pk-raise-go",()=>pokerAct("raise", parseInt(rng.value)));
      if(r.max>r.min) add(`全下 ${money(r.max)}`,"pk-allin",()=>pokerAct("allin"));
    }
  }else if(acts.allin!==undefined && !acts.call){
    add(`全下 ${money(acts.allin)}`,"pk-allin",()=>pokerAct("allin"));
  }
}
