"use strict";
window.BedtimeNameUnlock="data:audio/wav;base64,UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YSADAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==";
window.BedtimeAudio = class {
  constructor(audio, status, onEnded) {
    this.audio = audio;
    this.status = status;
    this.onEnded = onEnded;
    this.token = 0;
    this.nameToken = 0;
    this.generating = false;
    this.browser = false;
    this.chunks = [];
    this.index = 0;
    this.nameAudio = new Audio();
    audio.addEventListener("play", () => {
      this.nameToken++;
      this.nameAudio.pause();
      this.playingNameButton?.removeAttribute("aria-busy");
      this.playingNameButton?.setAttribute("aria-pressed","false");
      this.pronouncing=false;
      window.speechSynthesis?.cancel();
    });
    audio.addEventListener("ended", () => onEnded());
    audio.addEventListener("error", () => {
      status.textContent =
        "Audio could not play. Try Replay, or choose a device voice in Settings.";
    });
  }
  stop() {
    this.token++;
    this.nameToken++;
    this.generating = false;
    this.audio.pause();
    this.nameAudio.pause();
    this.playingNameButton?.removeAttribute("aria-busy");
    this.playingNameButton?.setAttribute("aria-pressed", "false");
    this.pronouncing = false;
    window.speechSynthesis?.cancel();
    this.status.closest(".audio-card")?.classList.remove("loading");
  }
  active() {
    return (
      (!this.audio.paused && !this.audio.ended) ||
      (!this.nameAudio.paused && !this.nameAudio.ended) ||
      Boolean(
        window.speechSynthesis?.speaking && !window.speechSynthesis?.paused,
      )
    );
  }
  async request(body, alive) {
    if (body.provider === "browser") return { fallback: true };
    let r = await fetch("/api/audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = await r.json();
    if (!r.ok) throw Error(data.detail || "Audio generation is unavailable");
    if (data.fallback) return data;
    while (["queued", "generating"].includes(data.state)) {
      if (!alive()) throw new DOMException("Stopped", "AbortError");
      await new Promise((resolve) => setTimeout(resolve, 700));
      r = await fetch("/api/audio/jobs/" + data.key);
      data = await r.json();
      if (!r.ok) throw Error("Could not check the audio job");
    }
    if (data.state !== "ready")
      throw Error(data.error || "Audio could not be generated");
    return data;
  }
  async prepare(text, prefs, overrides = {}) {
    this.stop();
    this.text = text;
    for (const [name, replacement] of Object.entries(overrides).sort(
      (a, b) => b[0].length - a[0].length,
    ))
      this.text = this.text.split(name).join(replacement);
    this.chunks = [];
    this.prefs = prefs;
    this.audio.removeAttribute("src");
    this.audio.load();
    this.browser = false;
    this.index = 0;
    const token = this.token;
    this.generating = true;
    this.status.textContent = "Getting your story ready…";
    this.status.closest(".audio-card").classList.add("loading");
    try {
      const data = await this.request(
        {
          kind: "narration",
          text,
          provider: prefs.narrationProvider,
          voice: prefs.narrationVoice,
          speed: 1,
          overrides,
        },
        () => token === this.token,
      );
      if (token !== this.token) return false;
      this.browser = Boolean(data.fallback);
      if (!this.browser) this.audio.src = data.url;
      this.status.textContent = this.browser
        ? "Using your device voice. Tap Play when you’re ready."
        : "Your story is ready. Tap Play.";
    } catch (e) {
      if (token !== this.token) return false;
      this.browser = true;
      this.status.textContent =
        "Local audio unavailable. Using your device voice; tap Play.";
    } finally {
      if (token === this.token) {
        this.generating = false;
        this.status.closest(".audio-card").classList.remove("loading");
      }
    }
    return token === this.token;
  }
  voice(uri) {
    return window.speechSynthesis
      ?.getVoices?.()
      .find((v) => v.voiceURI === uri);
  }
  speakChunk() {
    const token = this.token;
    if (this.index >= this.chunks.length) {
      this.onEnded();
      return;
    }
    const u = new SpeechSynthesisUtterance(this.chunks[this.index]);
    u.lang = "en-US";
    u.rate = this.prefs.narrationRate;
    const voice = this.voice(this.prefs.narrationVoice);
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    }
    u.onend = () => {
      if (token !== this.token) return;
      this.index++;
      this.speakChunk();
    };
    u.onerror = (e) => {
      if (
        token === this.token &&
        !["canceled", "interrupted"].includes(e.error)
      )
        this.status.textContent =
          "Device speech stopped. Try Replay or read along.";
    };
    speechSynthesis.speak(u);
  }
  async play() {
    if (this.generating) {
      this.status.textContent =
        "Getting your story ready… You can read along below.";
      return;
    }
    this.nameToken++;
    this.nameAudio.pause();
    if (this.browser) {
      if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
        this.status.textContent =
          "This device has no speech voice. Read along below.";
        return;
      }
      if (speechSynthesis.paused) {
        speechSynthesis.resume();
        return;
      }
      if (speechSynthesis.speaking) return;
      if (!this.chunks.length || this.index >= this.chunks.length) {
        this.chunks = this.text.match(/[^.!?\n]+[.!?]?/g) || [this.text];
        this.index = 0;
      }
      this.speakChunk();
      this.status.textContent =
        "Device narration · progress is unavailable for this fallback.";
    } else {
      window.speechSynthesis?.cancel();
      this.audio.playbackRate = this.prefs.narrationRate;
      try {
        await this.audio.play();
        this.status.textContent = "Settle in. Your adventure is playing.";
      } catch {
        this.status.textContent = "Tap Play on the audio player to begin.";
      }
    }
  }
  pause() {
    if (this.browser && window.speechSynthesis) {
      if (speechSynthesis.paused) speechSynthesis.resume();
      else speechSynthesis.pause();
    } else if (this.audio.paused) this.play();
    else this.audio.pause();
  }
  replay() {
    if (this.generating) return this.play();
    this.audio.currentTime = 0;
    window.speechSynthesis?.cancel();
    this.token++;
    this.index = 0;
    this.chunks = [];
    return this.play();
  }
  async previewPronunciation(creature, prefs, button) {
    this.audio.pause();
    this.nameAudio.pause();
    window.speechSynthesis?.cancel();
    if (!this.generating) this.token++;
    this.pronouncing = true;
    const token = ++this.nameToken;
    button?.setAttribute("aria-busy", "true");
    let text =
      prefs.guidedNames && creature.pronunciation
        ? creature.pronunciation.toLowerCase().replace(/sawr/g, "sore")
        : creature.name;
    const identity = JSON.stringify([
      creature.name,
      text,
      prefs.pronunciationProvider,
      prefs.pronunciationVoice,
      prefs.nameRate,
    ]);
    try {
      if (this.lastNameIdentity === identity && this.nameAudio.src) {
        this.nameAudio.currentTime = 0;
        try {
          await this.nameAudio.play();
        } catch {
          document.getElementById("message").textContent =
            "Pronunciation is ready. Tap the speaker again to play.";
        }
        return;
      }
      const data = await this.request(
        {
          kind: "pronunciation",
          text: creature.name,
          provider: prefs.pronunciationProvider,
          voice: prefs.pronunciationVoice,
          speed: prefs.nameRate,
          overrides: { [creature.name]: text },
        },
        () => token === this.nameToken,
      );
      if (token !== this.nameToken) return;
      if (!data.fallback) {
        this.nameAudio.src = data.url;
        this.lastNameIdentity = identity;
        try {
          await this.nameAudio.play();
        } catch {
          document.getElementById("message").textContent =
            "Pronunciation is ready. Tap the speaker again to play.";
        }
        return;
      }
      this.browserName(text, prefs);
    } catch (e) {
      if (token === this.nameToken) this.browserName(text, prefs);
    } finally {
      if (token === this.nameToken) this.pronouncing = false;
      button?.removeAttribute("aria-busy");
    }
  }
  async pronounce(creature, prefs, button) {
    this.audio.pause(); this.nameAudio.pause(); window.speechSynthesis?.cancel();
    const token=++this.nameToken;
    this.playingNameButton?.setAttribute("aria-pressed","false");
    this.playingNameButton?.removeAttribute("aria-busy");
    this.playingNameButton=button;this.pronouncing=true;
    if(button){button.dataset.nameToken=String(token);button.setAttribute("aria-busy","true");}
    const alive=()=>token===this.nameToken;
    const message=text=>{if(alive())document.getElementById("message").textContent=text;};
    const play=async(asset,recovered=false)=>{
      if(!alive())return false;
      this.audio.pause();window.speechSynthesis?.cancel();
      this.nameAudio.onended=()=>{if(alive())button?.setAttribute("aria-pressed","false");};
      this.nameAudio.onerror=null;
      this.nameAudio.src=asset.url+(recovered?"?recovered="+Date.now():"");
      this.nameAudio.currentTime=0;this.nameAudio.playbackRate=prefs.nameRate/(asset.speed||1);
      try{await this.nameAudio.play();if(alive()){button?.setAttribute("aria-pressed","true");message("");}return true;}
      catch(error){
        if(!alive())return false;
        if(error.name==="NotAllowedError") {message("Tap the picture or speaker again to play its name.");return true;}
        return false;
      }
    };
    try{
      if(prefs.pronunciationProvider==="browser") {this.browserName(creature.name,prefs);return;}
      const options=creature.pronunciation_audio_options||[];
      const asset=options.find(a=>a.provider===prefs.pronunciationProvider && a.voice===prefs.pronunciationVoice)||creature.pronunciation_audio||options[0];
      if(asset && /^\/api\/library\/pronunciations\/\d+\/[a-f0-9]{64}$/.test(asset.url)){
        if(await play(asset))return;
      }else{
        // Prime this same HTMLAudioElement within the tap on Safari. This tiny
        // silent UI unlock is not generated speech or a pronunciation claim.
        this.nameAudio.onerror=null;
        this.nameAudio.src=window.BedtimeNameUnlock;
        try{await this.nameAudio.play();if(alive())this.nameAudio.pause();}catch{}
      }
      await new Promise(resolve=>setTimeout(resolve,120));
      if(!alive())return;
      message("Getting this name ready…");
      const provider=prefs.pronunciationProvider==="piper"?"piper":"kokoro";
      const voice=provider===prefs.pronunciationProvider?prefs.pronunciationVoice:"af_heart";
      let response=await fetch(`/api/library/creatures/${creature.id}/pronunciation`,{
        method:"POST",headers:{"Content-Type":"application/json","X-Bedtime-Client":"app"},
        body:JSON.stringify({provider,voice,speed:prefs.nameRate})});
      let data=await response.json();if(!response.ok)throw Error("Name unavailable");
      while(["pending","generating"].includes(data.status)){
        await new Promise(resolve=>setTimeout(resolve,400));if(!alive())return;
        response=await fetch("/api/library/pronunciation-jobs/"+data.job_id);
        const jobId=data.job_id;data=await response.json();data.job_id=jobId;
        if(!response.ok)throw Error("Name unavailable");
      }
      if(!alive())return;
      if(data.status!=="ready"||!data.asset)throw Error("Name unavailable");
      creature.pronunciation_audio=data.asset;
      creature.pronunciation_audio_options=[data.asset,...options.filter(a=>a.url!==data.asset.url)];
      if(!await play(data.asset,true))throw Error("Playback unavailable");
    }catch{
      if(alive()){
        this.browserName(creature.name,prefs);
        message("Using a device voice for this name. You can tap again if it does not start.");
      }
    }finally{
      if(alive())this.pronouncing=false;
      if(button?.dataset.nameToken===String(token))button.removeAttribute("aria-busy");
    }
  }
  browserName(text, prefs) {
    if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
      document.getElementById("message").textContent =
        "This device has no pronunciation voice. The written guide is in Creature notes.";
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US";
    u.rate = prefs.nameRate;
    const v = this.voice(prefs.pronunciationVoice);
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  }
};
