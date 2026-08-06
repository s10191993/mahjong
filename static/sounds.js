"use strict";
// ============================================================
//  音效（Web Audio 即時合成，不需外部音檔）
//  用法：SFX.play("pong")、SFX.toggle()、SFX.enabled
// ============================================================
const SFX = (() => {
  let ctx = null;
  let enabled = localStorage.getItem("mj_sound") !== "off";

  function ac(){
    if(!ctx){
      const AC = window.AudioContext || window.webkitAudioContext;
      if(!AC) return null;
      ctx = new AC();
    }
    if(ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // 單顆音：頻率、起始時間、長度、音量、波形
  function tone(freq, at, dur, vol=0.22, type="triangle", slideTo=null){
    const c = ac(); if(!c) return;
    const t0 = c.currentTime + at;
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if(slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
    // 包絡：快起、指數衰減，聽起來像敲擊
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g); g.connect(c.destination);
    osc.start(t0); osc.stop(t0 + dur + 0.02);
  }

  // 敲牌的木頭聲（雜訊短促衰減）
  function knock(at=0, vol=0.35){
    const c = ac(); if(!c) return;
    const t0 = c.currentTime + at;
    const len = Math.floor(c.sampleRate * 0.06);
    const buf = c.createBuffer(1, len, c.sampleRate);
    const d = buf.getChannelData(0);
    for(let i=0;i<len;i++){
      d[i] = (Math.random()*2-1) * Math.pow(1 - i/len, 6);   // 白雜訊 + 快衰減
    }
    const src = c.createBufferSource(); src.buffer = buf;
    const bp = c.createBiquadFilter(); bp.type="bandpass";
    bp.frequency.value = 900; bp.Q.value = 1.2;
    const g = c.createGain(); g.gain.value = vol;
    src.connect(bp); bp.connect(g); g.connect(c.destination);
    src.start(t0);
  }

  const SOUNDS = {
    discard(){ knock(0, 0.3); },                                  // 打牌：叩
    draw_tile(){ tone(520, 0, 0.07, 0.10, "sine"); },             // 摸牌：輕點
    your_turn(){ tone(880, 0, 0.12, 0.18, "sine");
                 tone(1320, 0.10, 0.16, 0.14, "sine"); },         // 輪到你：叮咚
    chow(){ knock(0,0.28); tone(520, 0.02, 0.16, 0.20); },        // 吃
    pong(){ knock(0,0.32); tone(392, 0.02, 0.20, 0.24);
            tone(587, 0.06, 0.18, 0.18); },                       // 碰
    kong(){ knock(0,0.36); tone(330, 0.02, 0.26, 0.26);
            tone(494, 0.08, 0.24, 0.20);
            tone(659, 0.15, 0.22, 0.16); },                       // 槓
    hu(){                                                          // 胡：小號角
      [[523,0],[659,0.10],[784,0.20],[1047,0.32]].forEach(([f,t])=>
        tone(f, t, 0.34, 0.26, "triangle"));
    },
    multi_hu(){                                                    // 一炮多響：更澎湃
      [[523,0],[659,0.08],[784,0.16],[1047,0.26],[1319,0.38]].forEach(([f,t])=>
        tone(f, t, 0.42, 0.28, "sawtooth"));
    },
    lose(){ tone(392, 0, 0.5, 0.20, "sine", 180); },              // 放槍：下滑音
    draw_game(){ tone(300, 0, 0.5, 0.16, "sine", 200); },         // 流局
    flower(){ tone(1047, 0, 0.10, 0.14, "sine");
              tone(1319, 0.07, 0.12, 0.12, "sine"); },            // 補花
  };

  return {
    get enabled(){ return enabled; },
    toggle(){
      enabled = !enabled;
      localStorage.setItem("mj_sound", enabled ? "on" : "off");
      if(enabled) SOUNDS.your_turn();     // 開啟時試聽
      return enabled;
    },
    play(name){
      if(!enabled) return;
      const fn = SOUNDS[name];
      if(fn){ try{ fn(); }catch(e){} }
    },
    // 首次使用者互動時解鎖音訊（瀏覽器政策）
    unlock(){ try{ ac(); }catch(e){} },
  };
})();

document.addEventListener("pointerdown", () => SFX.unlock(), {once:true});
