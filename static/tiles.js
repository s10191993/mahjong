"use strict";
// ============================================================
//  牌面繪製（遊戲 client.js 與 牌面總覽 tiles.html 共用同一份）
//  改配色只要動這裡的 PIP_COLOR / honorColorClass。
// ============================================================
const NAME = {we:"東",ws:"南",ww:"西",wn:"北",dz:"中",df:"發",db:"白",
  f1:"春",f2:"夏",f3:"秋",f4:"冬",f5:"梅",f6:"蘭",f7:"菊",f8:"竹"};
const WIND_CN = {we:"東",ws:"南",ww:"西",wn:"北"};
const CN_NUM=["一","二","三","四","五","六","七","八","九"];
const HONOR_CHAR={we:"東",ws:"南",ww:"西",wn:"北",dz:"中",df:"發",db:"白"};
const FLOWER_CHAR={f1:"春",f2:"夏",f3:"秋",f4:"冬",f5:"梅",f6:"蘭",f7:"菊",f8:"竹"};

function tileName(c){
  if(NAME[c]) return NAME[c];
  const s={m:"萬",p:"筒",s:"條"}[c[0]]||"";
  return s? c[1]+s : c;
}

// 1~9 的點/竹排列（座標 %，還原傳統擺法）
const PIP_LAYOUT={
  1:[[50,50]],
  2:[[50,26],[50,74]],
  3:[[24,24],[50,50],[76,76]],
  4:[[30,30],[70,30],[30,70],[70,70]],
  5:[[30,30],[70,30],[50,50],[30,70],[70,70]],
  6:[[27,33],[50,33],[73,33],[27,67],[50,67],[73,67]],   // 2 列 × 3 行
  7:[[27,17],[50,17],[73,17],[50,50],[27,83],[50,83],[73,83]],
  8:[[34,14],[66,14],[34,38],[66,38],[34,62],[66,62],[34,86],[66,86]],  // 2 直行 × 4 列
  9:[[24,20],[50,20],[76,20],[24,50],[50,50],[76,50],[24,80],[50,80],[76,80]]
};
const DOT_COLORS=["c-green","c-red","c-dark"];  // 未指定時的交錯預設
// 各號碼點/竹的固定配色（單一色字串＝整顆同色；陣列＝逐顆，順序同 PIP_LAYOUT）
const G="c-green", R="c-red", B="c-blue", K="c-dark";
const PIP_COLOR={
  p:{ // 筒
    1:G, 2:G, 3:G, 4:B,
    5:[B,B,R,B,B],                 // 藍角 + 紅心
    6:[G,G,G,R,R,R],               // 上綠 下紅
    7:[R,R,R,G,G,G,G],             // 上排紅、中+下綠
    8:K,                           // 全黑
    9:[G,G,G,R,R,R,B,B,B]          // 上綠 中紅 下藍
  },
  s:{ // 條（以綠為主）
    1:R, 2:G, 3:G, 4:G,
    5:[G,G,R,G,G],                 // 中心紅
    6:G,
    7:[R,R,R,G,G,G,G],             // 上排紅
    8:G,
    9:[G,R,G,G,R,G,G,R,G]          // 中央直行紅
  }
};
function pipColorClass(suit,n,idx){
  const ov=PIP_COLOR[suit] && PIP_COLOR[suit][n];
  if(ov) return Array.isArray(ov)? ov[idx%ov.length] : ov;
  return suit==="p"? DOT_COLORS[idx%3] : ["c-green","c-dark","c-red"][idx%3];
}

function honorColorClass(code){
  if(code==="dz") return "c-red";     // 中
  if(code==="df") return "c-green";   // 發
  if(code==="db") return "c-blue";    // 白
  if(FLOWER_CHAR[code]) return ["f1","f6","f8"].includes(code)?"c-green"
                              :code==="f4"?"c-blue":"c-red";
  return "c-black";                   // 東南西北
}

// 圖檔設定：把牌面圖放到 /static/tiles/ ，檔名＝牌代碼（見下）。
// 有圖就用圖，缺圖自動退回自繪牌面。
const TILE_IMG_DIR="/static/tiles/";
const TILE_IMG_EXTS=[".png",".jpg",".jpeg",".webp"];  // 依序嘗試的副檔名
let TILE_IMAGES=true;
// 牌背預設用內建斜紋；若你放了 tiles/back.png，把這行改成 true
const USE_BACK_IMAGE=false;
const MISSING_IMG=new Set();   // 記住哪些牌沒圖，之後直接自繪不再重複請求

function tileEl(code, cls=""){
  const d=document.createElement("div");
  d.className="tile "+cls;
  d.dataset.code=code;
  const isBack=/\bback\b/.test(cls);
  if(isBack && !USE_BACK_IMAGE) return d;        // 牌背用 CSS 斜紋
  const key=isBack?"back":code;
  if(TILE_IMAGES && !MISSING_IMG.has(key)){
    addTileImg(d, key, isBack? null : ()=>drawFace(d,code,cls));
  }else if(!isBack){
    drawFace(d,code,cls);
  }
  return d;
}

function addTileImg(d, code, onFail){
  const img=document.createElement("img");
  img.className="tile-img"; img.alt=code; img.draggable=false;
  let i=0;
  img.onerror=()=>{
    i++;
    if(i<TILE_IMG_EXTS.length){ img.src=TILE_IMG_DIR+code+TILE_IMG_EXTS[i]; }
    else { MISSING_IMG.add(code); img.remove(); if(onFail) onFail(); }
  };
  img.src=TILE_IMG_DIR+code+TILE_IMG_EXTS[0];
  d.appendChild(img);
}

function drawFace(d, code, cls){
  const suit=code[0];
  const face=document.createElement("div"); face.className="face";

  // 牌河 / 亮牌等小牌：用精簡文字（好辨識）
  if(/\b(small|mini)\b/.test(cls)){
    face.classList.add("f-compact");
    if(HONOR_CHAR[code]||FLOWER_CHAR[code]){
      const ch=document.createElement("span");
      ch.className="cmp-h "+honorColorClass(code);
      ch.textContent=HONOR_CHAR[code]||FLOWER_CHAR[code];
      face.appendChild(ch);
    }else{
      const num=document.createElement("span"); num.className="cmp-n"; num.textContent=code[1];
      const su=document.createElement("span");
      su.className="cmp-s "+{m:"c-red",p:"c-blue",s:"c-green"}[suit];
      su.textContent={m:"萬",p:"筒",s:"條"}[suit];
      face.append(num,su);
    }
    d.appendChild(face); return d;
  }

  // 大牌：完整圖形牌面
  if(suit==="m"){
    face.classList.add("f-man");
    const num=document.createElement("span"); num.className="m-num"; num.textContent=CN_NUM[+code[1]-1];
    const wan=document.createElement("span"); wan.className="m-wan"; wan.textContent="萬";
    face.append(num,wan);
  }else if(suit==="p"||suit==="s"){
    const n=+code[1];
    face.classList.add("f-pips");
    PIP_LAYOUT[n].forEach((pos,idx)=>{
      const pip=document.createElement("div");
      pip.style.left=pos[0]+"%"; pip.style.top=pos[1]+"%";
      pip.className="pip "+(suit==="p"?"pip-dot ":"pip-stick ")+pipColorClass(suit,n,idx);
      if(n===1 && suit==="p") pip.classList.add("pip-big");   // 1筒：大圈
      face.appendChild(pip);
    });
  }else if(code==="db"){
    face.classList.add("f-bai");                // 白：藍框
  }else if(HONOR_CHAR[code]||FLOWER_CHAR[code]){
    face.classList.add("f-honor");
    const ch=document.createElement("span"); ch.className="h-char "+honorColorClass(code);
    ch.textContent=HONOR_CHAR[code]||FLOWER_CHAR[code];
    face.appendChild(ch);
  }
  d.appendChild(face); return d;
}
