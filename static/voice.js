"use strict";
// ============================================================
//  語音聊天（WebRTC 點對點）
//
//  音訊直接在玩家之間傳，伺服器只轉發「牽線用」的 offer/answer/ICE，
//  完全不碰語音資料 —— 免費主機的頻寬撐不起中繼，這樣也延遲最低。
//
//  注意：多數家用網路可直連；少數行動網路（電信 CGNAT）需要 TURN 中繼，
//  沒設 TURN 時那些人可能連不上，會顯示「連線中」。
// ============================================================
const Voice = (() => {
  const RTC_CONF = {
    iceServers: [
      { urls: "stun:stun.l.google.com:19302" },
      { urls: "stun:stun1.l.google.com:19302" },
    ],
  };

  let localStream = null;
  let enabled = false;      // 是否已開語音
  let muted = false;        // 是否閉麥
  let mySeat = null;
  let sendFn = () => {};
  let onUpdate = () => {};
  const peers = {};         // seat -> {pc, audio, analyser, data, level, state}
  let levelTimer = null;
  let localAnalyser = null, localData = null, localLevel = 0;

  function log(...a) { /* console.log("[voice]", ...a); */ }

  // ---- 音量偵測（誰在講話）----------------------------------------------
  function makeAnalyser(stream) {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      const ctx = makeAnalyser._ctx || (makeAnalyser._ctx = new AC());
      if (ctx.state === "suspended") ctx.resume();
      const src = ctx.createMediaStreamSource(stream);
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.6;
      src.connect(an);
      return { analyser: an, data: new Uint8Array(an.frequencyBinCount) };
    } catch (e) { return null; }
  }
  function rms(analyser, data) {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / data.length);
  }
  function tickLevels() {
    if (localAnalyser) localLevel = muted ? 0 : rms(localAnalyser, localData);
    for (const s in peers) {
      const p = peers[s];
      if (p.analyser) p.level = rms(p.analyser, p.data);
    }
    onUpdate();
  }

  // ---- 連線 --------------------------------------------------------------
  function makePeer(seat) {
    if (peers[seat]) return peers[seat];
    const pc = new RTCPeerConnection(RTC_CONF);
    const entry = { pc, audio: null, analyser: null, data: null, level: 0,
                    state: "connecting" };
    peers[seat] = entry;

    if (localStream) {
      localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
    }
    pc.onicecandidate = (e) => {
      if (e.candidate) sendFn({ t: "rtc", to: +seat, kind: "ice", data: e.candidate });
    };
    pc.ontrack = (e) => {
      const stream = e.streams[0];
      let el = entry.audio;
      if (!el) {
        el = document.createElement("audio");
        el.autoplay = true;
        el.playsInline = true;
        el.dataset.seat = seat;
        document.body.appendChild(el);
        entry.audio = el;
      }
      el.srcObject = stream;
      el.play().catch(() => {});
      const a = makeAnalyser(stream);
      if (a) { entry.analyser = a.analyser; entry.data = a.data; }
      entry.state = "connected";
      onUpdate();
    };
    pc.onconnectionstatechange = () => {
      entry.state = pc.connectionState;
      if (["failed", "closed", "disconnected"].includes(pc.connectionState)) {
        onUpdate();
      }
    };
    return entry;
  }

  async function callPeer(seat) {
    const { pc } = makePeer(seat);
    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    sendFn({ t: "rtc", to: +seat, kind: "offer", data: pc.localDescription });
  }

  function dropPeer(seat) {
    const p = peers[seat];
    if (!p) return;
    try { p.pc.close(); } catch (e) {}
    if (p.audio) p.audio.remove();
    delete peers[seat];
    onUpdate();
  }

  // ---- 對外 API ----------------------------------------------------------
  return {
    init(opts) {
      sendFn = opts.send;
      onUpdate = opts.onUpdate || (() => {});
    },
    setSeat(s) { mySeat = s; },
    get enabled() { return enabled; },
    get muted() { return muted; },
    get supported() {
      return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia
                && window.RTCPeerConnection);
    },
    peerState(seat) { return peers[seat] ? peers[seat].state : null; },
    isSpeaking(seat) {
      if (seat === mySeat) return enabled && !muted && localLevel > 0.045;
      const p = peers[seat];
      return !!(p && p.level > 0.045);
    },

    async enable() {
      if (enabled) return true;
      if (!this.supported) throw new Error("這個瀏覽器不支援語音");
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,     // 不開會有回音（大家都開喇叭時很嚴重）
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      const a = makeAnalyser(localStream);
      if (a) { localAnalyser = a.analyser; localData = a.data; }
      enabled = true; muted = false;
      sendFn({ t: "voice_state", on: true });
      if (!levelTimer) levelTimer = setInterval(tickLevels, 150);
      onUpdate();
      return true;
    },

    disable() {
      enabled = false;
      sendFn({ t: "voice_state", on: false });
      Object.keys(peers).forEach(dropPeer);
      if (localStream) {
        localStream.getTracks().forEach(t => t.stop());
        localStream = null;
      }
      localAnalyser = null; localLevel = 0;
      clearInterval(levelTimer); levelTimer = null;
      onUpdate();
    },

    toggleMute() {
      if (!enabled) return false;
      muted = !muted;
      if (localStream) localStream.getAudioTracks().forEach(t => t.enabled = !muted);
      onUpdate();
      return muted;
    },

    /** 伺服器告知目前有誰開著語音 → 建立/清掉連線 */
    syncPeers(list) {
      if (!enabled || mySeat === null) return;
      const want = (list || []).filter(s => s !== mySeat);
      // 已經不在名單上的就斷開
      Object.keys(peers).forEach(s => {
        if (!want.includes(+s)) dropPeer(s);
      });
      // 為避免雙方同時發 offer 撞在一起，固定由「座位號小的」發起
      want.forEach(s => {
        if (peers[s]) return;
        if (mySeat < s) callPeer(s);
        else makePeer(s);          // 等對方的 offer
      });
    },

    /** 收到伺服器轉來的信令 */
    async signal(m) {
      if (!enabled) return;
      const seat = m.from;
      const entry = makePeer(seat);
      const pc = entry.pc;
      try {
        if (m.kind === "offer") {
          await pc.setRemoteDescription(new RTCSessionDescription(m.data));
          const ans = await pc.createAnswer();
          await pc.setLocalDescription(ans);
          sendFn({ t: "rtc", to: seat, kind: "answer", data: pc.localDescription });
        } else if (m.kind === "answer") {
          await pc.setRemoteDescription(new RTCSessionDescription(m.data));
        } else if (m.kind === "ice") {
          await pc.addIceCandidate(new RTCIceCandidate(m.data));
        }
      } catch (e) { log("signal error", e); }
    },
  };
})();
