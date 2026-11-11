"use strict";
window.PersistentChapters = (() => {
  let viewing = null, preparing = false, voiceChanged = false;
  let question="want", lastCompleted=null;
  let positions={};try{positions=JSON.parse(sessionStorage.getItem("bedtimeBracketPositions")||"{}");}catch{}
  const post = (path, body={}) => api(path, {method:"POST",headers:{"Content-Type":"application/json","X-Bedtime-Client":"app"},body:JSON.stringify(body)});
  const path = (bid) => `/api/story/tournaments/${current.id}/battles/${bid}`;
  async function create(ids) {
    audio.stop();
    current = await post("/api/story/tournaments",{creature_ids:ids,shuffle:settings.get().shuffle,request_key:(globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+"-"+Math.random().toString(36).slice(2)+"-"+Math.random().toString(36).slice(2))});
    save();renderBracket();show("bracket");
  }
  function portraits(participants) {
    $("battle-creatures").replaceChildren();
    for (const creature of participants) {
      const card=document.createElement("div");card.className="battle-portrait";
      const label=document.createElement("h2");label.textContent=creature.name;
      card.append(picture(creature),label,hear(creature));$("battle-creatures").append(card);
    }
  }
  function remember(bid) {
    if(!current?.id || screen!=="bracket")return;
    const scroller=$("bracket-scroll");
    const card=[...document.querySelectorAll('#rounds [data-battle]')].find(c=>c.dataset.battle===bid);
    positions[current.id]={y:window.scrollY,x:scroller.scrollLeft,innerY:scroller.scrollTop,bid,top:card?.getBoundingClientRect().top};
    try{sessionStorage.setItem("bedtimeBracketPositions",JSON.stringify(positions));}catch{}
  }
  function restoreBracket() {
    const point=positions[current?.id];
    if(!point){window.scrollTo({top:0,behavior:"instant"});return;}
    const scroller=$("bracket-scroll");scroller.scrollLeft=point.x||0;scroller.scrollTop=point.innerY||0;
    const card=[...document.querySelectorAll('#rounds [data-battle]')].find(c=>c.dataset.battle===point.bid);
    window.scrollTo({top:Math.max(0,card && Number.isFinite(point.top)?window.scrollY+card.getBoundingClientRect().top-point.top:point.y),behavior:"instant"});
  }
  function ask(kind) {
    question=kind;$("battle-question").textContent=kind==="want"?"Who do you WANT to win?":"Who do you THINK will win?";
    $("question-stage").textContent=kind==="want"?"CHOOSE OR SKIP":"MAKE A GUESS OR SKIP";
    $("prediction-skip").textContent="Skip";
    $("prediction-skip").setAttribute("aria-label",kind==="want"?"Skip desired winner":"Skip prediction");
    $("prediction-choices").replaceChildren();
    for(const c of viewing.participants){
      const button=document.createElement("button");button.className="creature-pick";
      const name=document.createElement("strong");name.textContent=c.name;
      button.append(picture(c),name);button.onclick=()=>answer(c.id);
      $("prediction-choices").append(button);
    }
    show("prediction");
  }
  async function answer(id) {
    if(preparing)return;
    if(question==="think")return begin(id,id===null);
    preparing=true;
    try{
      const data=await post(path(viewing.bid)+"/desire",{desired_winner_id:id});
      viewing.desired=data.desired_choice;
      if(data.prediction || data.status!=="not_started"){preparing=false;return present(data);}
      if(data.predictions_enabled)ask("think");
      else{preparing=false;return begin(null,true);}
    }catch{$("message").textContent="That choice needs a moment. Please try again.";}
    finally{preparing=false;}
  }
  async function open(bid) {
    if(!current?.id)return;
    bid=bid || current.chapter?.battle_id;if(!bid)return;
    remember(bid);
    current=await api(`/api/story/tournaments/${current.id}`);save();
    const match=current.rounds.flatMap(r=>r.matches).find(m=>m.battle_id===bid);
    if(!match?.left || !match?.right)return;
    const data=await api(path(bid));
    viewing={bid,participants:[match.left,match.right],completed:data.completed,replay:data.completed,prediction:data.prediction,desired:data.desired_choice};
    if(!data.completed && !data.prediction){
      if(!data.desired_choice)return ask("want");
      if(data.predictions_enabled)return ask("think");
    }
    if(data.status==="not_started")return begin(data.prediction?.predicted_winner_id ?? null,data.prediction?.skipped ?? true);
    await present(data);
  }
  async function begin(predicted,skipped) {
    if (preparing || !viewing) return;
    preparing=true;
    try {
      const prefs=settings.get();
      const audioPrefs=(!voiceChanged && current.audio_preferences) || {provider:prefs.narrationProvider,voice:prefs.narrationVoice,speed:prefs.narrationRate};
      const data=await post(path(viewing.bid)+"/begin",{desired_winner_id:viewing.desired?.desired_winner_id ?? null,predicted_winner_id:predicted,skipped,
        audio:audioPrefs});
      voiceChanged=false;
      viewing.prediction=data.prediction;
      await present(data);
    } catch {$("message").textContent="That chapter needs a moment. Please try again.";}
    finally {preparing=false;}
  }
  async function present(data) {
    const id=++loadId;
    audio.stop();portraits(viewing.participants);show("player");
    $("battle-label").textContent=`CHAPTER ${data.chapter_number} OF 7`;
    $("chapter-title").textContent=data.narrative?.title || "Your adventure is getting ready…";
    $("chapter-text").replaceChildren();$("finish").disabled=true;
    $("audio-status").textContent="Getting your chapter ready…";
    audio.generating=true;
    while (["pending","generating"].includes(data.status)) {
      await new Promise(resolve=>setTimeout(resolve,600));
      if (id!==loadId || screen!=="player") return;
      data=await api(path(viewing.bid));
    }
    audio.generating=false;
    if (id!==loadId || screen!=="player") return;
    if (!data.narrative) {$("audio-status").textContent="The story is taking a rest. Ask a grown-up to try again.";return;}
    $("chapter-title").textContent=data.narrative.title;
    for (const paragraph of data.narrative.paragraphs) profileParagraph($("chapter-text"),paragraph);
    viewing.ending=data.narrative.ending;
    const text=[...data.narrative.paragraphs,data.narrative.ending].join("\n\n");
    $("finish").disabled=false;
    $("retry-chapter").hidden=data.status!=="failed";
    if (data.audio?.url && data.status==="ready") {
      audio.stop();audio.text=text;audio.browser=false;audio.prefs={...settings.get(),narrationRate:1};
      audio.audio.src=data.audio.url;audio.audio.load();$("story-rate").value="1";
      $("audio-status").textContent=`Ready · ${Math.round(data.audio.actual_seconds)} seconds`+
        (data.audio.timing_met?"":" · the closest natural narration timing");
    } else {
      await audio.prepare(text,{...settings.get(),narrationProvider:"browser"});
      $("audio-status").textContent="Local narration is resting. Read along or use your device voice; timing is not measured.";
    }
    if (settings.get().autoNarration) audio.play();
  }
  async function finish() {
    if (!viewing || screen!=="player") return;
    const bid=viewing.bid;
    const result=viewing.completed ? current : await post(path(bid)+"/complete");
    audio.stop();current=result;lastCompleted=bid;save();renderBracket();
    const match=current.rounds.flatMap(r=>r.matches).find(m=>m.battle_id===bid);
    const prediction=current.history.find(h=>h.battle_id===bid)?.prediction;
    $("chapter-winner-name").textContent=match.winner.name;
    $("chapter-reveal-ending").textContent=viewing.ending || "";
    $("chapter-winner-picture").replaceChildren(picture(match.winner));
    $("prediction-response").textContent=prediction?.skipped?"What an adventure!":prediction?.correct?"You guessed it!":"What an amazing battle!";
    $("next-chapter").textContent=viewing.replay?"Back to the adventure path":"Follow the adventure →";
    viewing.completed=true;show("chapter-reveal");
  }
  $("retry-chapter").onclick=()=>begin(viewing?.prediction?.predicted_winner_id ?? null,viewing?.prediction?.skipped ?? true);
  document.getElementById("duration").closest("label").hidden=true;
  document.getElementById("realism").closest("label").hidden=true;
  $("prediction-skip").onclick=()=>answer(null);
  $("next-chapter").onclick=()=>current.champion && !viewing?.replay?celebrate():(renderBracket(),show("bracket"));
  const historyButton=document.createElement("button");historyButton.id="saved-adventures";historyButton.textContent="Our saved adventures";
  $("welcome").append(historyButton);
  historyButton.onclick=async()=>{
    $("adventure-history-list").replaceChildren();
    async function load(offset) {
      const rows=await api(`/api/story/tournaments?offset=${offset}&limit=20`);
      for(const row of rows){
        const button=document.createElement("button");button.textContent=`${row.title} · ${row.completed}/7 chapters · ${new Date(row.created).toLocaleString()}`;
        button.onclick=async()=>{current=await api(`/api/story/tournaments/${row.id}`);save();renderBracket();show("bracket");};
        $("adventure-history-list").append(button);
      }
      if(!rows.length && offset===0)profileParagraph($("adventure-history-list"),"New adventures will be saved here.");
      if(rows.length===20){
        const more=document.createElement("button");more.textContent="More saved adventures";
        more.onclick=async()=>{more.remove();await load(offset+20);};$("adventure-history-list").append(more);
      }
    }
    await load(0);show("adventure-history");
  };
  const safe = fn => async (...args) => {
    try { return await fn(...args); }
    catch { audio.generating=false; $("message").textContent="Your adventure is safe. Please try again when the server is ready."; }
  };
  return {create,open:safe(open),finish:safe(finish),viewing:()=>viewing,audioChanged:()=>{voiceChanged=true;},restoreBracket,completedBattle:()=>lastCompleted};
})();
