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

// ---- 籌碼圖案 --------------------------------------------------------------
// 面額與顏色（賭場常見配色）
const CHIP_DENOMS = [
  {v:1000, cls:"c1000"}, {v:500, cls:"c500"}, {v:100, cls:"c100"},
  {v:25, cls:"c25"}, {v:5, cls:"c5"}, {v:1, cls:"c1"},
];
function chipBreakdown(amount, maxChips=14){
  const out=[]; let left=Math.max(0, Math.round(amount));
  for(const d of CHIP_DENOMS){
    let n=Math.floor(left/d.v);
    if(n>0){ left-=n*d.v; out.push({...d, n}); }
  }
  // 總數過多就壓縮（只顯示大面額，避免畫面爆掉）
  let total=out.reduce((a,b)=>a+b.n,0);
  while(total>maxChips && out.length){
    const last=out[out.length-1];
    total-=last.n; out.pop();
  }
  return out;
}
function chipStackEl(amount, cls=""){
  const wrap=document.createElement("div");
  wrap.className="chips "+cls;
  chipBreakdown(amount).forEach(d=>{
    const col=document.createElement("div"); col.className="chip-col";
    for(let i=0;i<Math.min(d.n,6);i++){
      const c=document.createElement("div");
      c.className="chip "+d.cls;
      c.style.bottom=(i*4)+"px";
      col.appendChild(c);
    }
    if(d.n>6){
      const lb=document.createElement("span"); lb.className="chip-x";
      lb.textContent="×"+d.n; col.appendChild(lb);
    }
    wrap.appendChild(col);
  });
  return wrap;
}

// 依「我」的座位把其他人排在桌子周圍。
// 我固定在正下方，其他人沿「上半橢圓弧」由左下 → 上方 → 右下排開，
// 刻意避開畫面下緣（那是我的手牌與下注按鈕區），滿 8 人也不會互相遮擋。
function seatPositions(mySeat, seats){
  const others=seats.filter(s=>s!==mySeat);
  const n=others.length;
  const pos={};
  if(n===0) return pos;
  if(n===1){ pos[others[0]]={x:50, y:20}; return pos; }
  // 橫向鋪開（畫面是橫的，寬度才是資源），中間高、兩端低，像坐在桌子對面。
  // 相鄰間距 = 88%/(n-1)，8 人時仍有 ~124px，遠大於座位寬度，不會互相遮擋。
  for(let i=0;i<n;i++){
    const t=i/(n-1);
    pos[others[i]] = {x: 6 + 88*t, y: 40 - 22*Math.sin(Math.PI*t)};
  }
  return pos;
}

function renderPoker(pub, pri, mySeat){
  const seated=pub.players.filter(p=>p.name).map(p=>p.seat);
  document.getElementById("pk-blinds").textContent=
    `盲注 ${money(pub.small_blind)}/${money(pub.big_blind)}`;
  document.getElementById("pk-handno").textContent=`第 ${pub.hand_no} 手`;
  document.getElementById("pk-phase").textContent=PHASE_CN[pub.phase]||pub.phase;

  // 底池（文字 + 籌碼圖案）
  const potBox=document.getElementById("pk-pot"); potBox.innerHTML="";
  if(pub.pot>0){
    potBox.appendChild(chipStackEl(pub.pot, "pot-chips"));
    const lb=document.createElement("div"); lb.className="pot-label";
    lb.innerHTML=`底池 <b>${money(pub.pot)}</b>`;
    potBox.appendChild(lb);
  }

  // 公牌（新出現的牌加翻牌動畫）
  const bc=document.getElementById("pk-board-cards");
  const prevBoard=renderPoker._board||[];
  const nowBoard=pub.board||[];
  const sameHand = renderPoker._hand===pub.hand_no;
  bc.innerHTML="";
  nowBoard.forEach((c,i)=>{
    const el=cardEl(c);
    if(!sameHand || i>=prevBoard.length){          // 這次新翻出來的
      el.classList.add("deal-flip");
      el.style.animationDelay=(sameHand ? (i-prevBoard.length) : i)*110+"ms";
    }
    bc.appendChild(el);
  });
  for(let i=nowBoard.length;i<5;i++){
    const ph=document.createElement("div"); ph.className="pcard slot"; bc.appendChild(ph);
  }
  renderPoker._board=[...nowBoard];

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
    // 橫向緊湊排版：左邊牌、右邊名字/籌碼，高度才壓得下（8 人也不互相遮擋）
    el.innerHTML =
      `<div class="pk-row">${showCards}`+
      `<div class="pk-txt">`+
        `<div class="pk-name">${p.seat===pub.button?'<span class="btn-d">D</span>':''}`+
        `${escapeHtml(p.name)}</div>`+
        `<div class="pk-stack">${money(p.stack)}</div>`+
      `</div></div>`+
      (p.bet>0?`<div class="pk-bet"><span class="chip c-inline"></span>${money(p.bet)}</div>`:"")+
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
    const newHand = renderPoker._hand!==pub.hand_no;
    (pri.hole||[]).forEach((c,i)=>{
      const el=cardEl(c, me.folded?"dim":"");
      if(newHand){                                  // 新的一手：發牌動畫
        el.classList.add("deal-in");
        el.style.animationDelay=(i*130)+"ms";
      }
      cw.appendChild(el);
    });
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
  renderPoker._hand=pub.hand_no;
}

function renderPokerActions(pub, pri, mySeat){
  const bar=document.getElementById("pk-actions"); bar.innerHTML="";
  const nextBtn=document.getElementById("pk-next");
  nextBtn.style.display = (pub.phase==="over") ? "" : "none";

  // 補碼（籌碼低於 300 且不在牌局中）
  if(pri.can_rebuy){
    const rb=document.createElement("div"); rb.className="pk-rebuy";
    const lb=document.createElement("span"); lb.className="pk-rebuy-lb";
    lb.textContent="籌碼不足，補碼：";
    rb.appendChild(lb);
    (pri.rebuy_options||[500,1000]).forEach(amt=>{
      const b=document.createElement("button");
      b.className="pk-btn pk-rebuy-btn"; b.textContent="+"+money(amt);
      b.onclick=()=> send({t:"rebuy", amount:amt});
      rb.appendChild(b);
    });
    bar.appendChild(rb);
  }

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
      return;
    }
    const clamp=(v)=> Math.max(r.min, Math.min(r.max, Math.round(v)));
    const wrap=document.createElement("div"); wrap.className="pk-raise";

    // 目前選定的加注額（可用比例鈕、滑桿、手動輸入）
    const row=document.createElement("div"); row.className="pk-raise-row";
    const num=document.createElement("input");
    num.type="number"; num.className="pk-raise-num";
    num.min=r.min; num.max=r.max; num.step=1; num.value=r.min;
    const rng=document.createElement("input");
    rng.type="range"; rng.min=r.min; rng.max=r.max; rng.step=1; rng.value=r.min;
    const goBtn=document.createElement("button");
    goBtn.className="pk-btn pk-raise-go";
    const sync=(v)=>{
      const t=clamp(v);
      num.value=t; rng.value=t;
      goBtn.textContent=`加注到 ${money(t)}`;
    };
    num.oninput=()=>{ rng.value=clamp(num.value); goBtn.textContent=`加注到 ${money(clamp(num.value))}`; };
    num.onblur=()=> sync(num.value);
    rng.oninput=()=> sync(rng.value);
    goBtn.onclick=()=> pokerAct("raise", clamp(num.value));

    // 比例快捷：以底池為基準加注（加注到 = 目前注 + 比例×底池）
    const quick=document.createElement("div"); quick.className="pk-quick";
    const pot=Math.max(pub.pot, pub.big_blind);
    [["1/3",1/3],["1/2",1/2],["2/3",2/3],["3/4",3/4],["1×",1]].forEach(([lb,f])=>{
      const target=clamp(pub.current_bet + pot*f);
      const b=document.createElement("button");
      b.className="pk-mini-btn"; b.textContent=lb;
      b.title=`加注到 ${money(target)}`;
      b.onclick=()=> sync(target);
      quick.appendChild(b);
    });
    const ab=document.createElement("button");
    ab.className="pk-mini-btn pk-mini-allin"; ab.textContent="All in";
    ab.onclick=()=> pokerAct("allin");
    quick.appendChild(ab);

    row.append(num, rng);
    wrap.append(quick, row);
    bar.appendChild(wrap);
    bar.appendChild(goBtn);
    sync(r.min);
  }else if(acts.allin!==undefined && !acts.call){
    add(`全下 ${money(acts.allin)}`,"pk-allin",()=>pokerAct("allin"));
  }
}
