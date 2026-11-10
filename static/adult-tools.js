"use strict";
(() => {
  const el=id=>document.getElementById(id);
  let csrf=null,creatures=[],searchId=null,offset=null,sessionEpoch=0;
  async function request(path,body,method="POST") {
    const response=await fetch("/api/admin/"+path,{method:body?method:"GET",headers:body?{"Content-Type":"application/json","X-Parent-CSRF":csrf||""}:{},body:body?JSON.stringify(body):undefined});
    const data=await response.json();
    if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Please check the request and try again.");
    return data;
  }
  function status(text){el("adult-status").textContent=text;}
  async function refreshSession(){
    const epoch=++sessionEpoch;
    const session=await request("session");if(epoch!==sessionEpoch)return;csrf=session.csrf;
    el("adult-tools").hidden=!session.unlocked;
    status(session.unlocked?"Grown-up controls are unlocked.":session.configured?"Enter the parent passphrase to unlock.":"Set a parent passphrase on the server using scripts/configure_parent.py, then unlock here.");
    if(session.unlocked){
      const prefs=await api("/api/story/settings");
      el("battle-duration").value=String(prefs.duration_seconds);el("battle-predictions").checked=prefs.predictions_enabled;
      el("battle-tone").value=prefs.tone;el("battle-connected").checked=prefs.connected_chapters;
      creatures=await api("/api/creatures");filter();
    }
  }
  function action(id,fn){el(id).onclick=async()=>{const b=el(id);b.disabled=true;try{await fn();}catch(error){status(error.message);}finally{b.disabled=false;}};}
  action("adult-unlock",async()=>{sessionEpoch++;try{await request("login",{password:el("adult-password").value});}finally{el("adult-password").value="";}await refreshSession();});
  action("adult-lock",async()=>{sessionEpoch++;await request("logout",{});csrf=null;await refreshSession();});
  action("save-battle-settings",async()=>{await request("story/settings",{duration_seconds:Number(el("battle-duration").value),tone:el("battle-tone").value,predictions_enabled:el("battle-predictions").checked,connected_chapters:el("battle-connected").checked,winner_mode:"simulation"},"PUT");status("Saved. New settings apply to chapters that have not been prepared.");});
  action("view-chapter-versions",async()=>{
    const bid=PersistentChapters.viewing()?.bid || current?.chapter?.battle_id;
    if(!current?.id || !bid)throw Error("Open a saved chapter first.");
    const versions=await request(`story/tournaments/${current.id}/battles/${bid}/versions`);
    el("chapter-versions").replaceChildren();
    for(const version of versions){
      const block=document.createElement("article");
      profileParagraph(block,`Version ${version.revision} · ${version.narrative?.title || "Chapter"}`);
      if(version.audio){
        profileParagraph(block,`${version.audio.actual_seconds.toFixed(1)} seconds · ${version.audio.provider} · ${version.audio.voice}`);
        const player=document.createElement("audio");player.controls=true;player.preload="none";player.src=version.audio.url;block.append(player);
      }
      const text=document.createElement("details"),label=document.createElement("summary");label.textContent="Read this version";text.append(label);
      for(const paragraph of [...(version.narrative?.paragraphs || []),version.narrative?.ending || ""])profileParagraph(text,paragraph);
      block.append(text);el("chapter-versions").append(block);
    }
  });
  el("regenerate-chapter").onclick=()=>{el("regenerate-confirm").hidden=false;};
  el("regenerate-cancel").onclick=()=>{el("regenerate-confirm").hidden=true;};
  action("regenerate-confirm-yes",async()=>{
    const viewing=PersistentChapters.viewing();const bid=viewing?.bid || current?.chapter?.battle_id;
    if(!current?.id || !bid)throw Error("Open the saved chapter you want to regenerate first.");
    await request(`story/tournaments/${current.id}/battles/${bid}/regenerate`,{confirm:true});
    el("regenerate-confirm").hidden=true;status("New version queued. Outcome and original audio are preserved.");
  });
  function selected(){return creatures.find(c=>c.id===Number(el("manage-creature").value));}
  function filter(){
    const term=el("manage-creature-search").value.toLowerCase();const old=el("manage-creature").value;
    const rows=creatures.filter(c=>`${c.name} ${c.scientific_name} ${c.category}`.toLowerCase().includes(term));
    el("manage-creature").replaceChildren(...rows.map(c=>new Option(c.name+" · "+c.category,c.id)));
    if(rows.some(c=>String(c.id)===old))el("manage-creature").value=old;
    showCreature().catch(e=>status(e.message));
  }
  el("manage-creature-search").oninput=filter;
  el("manage-creature").onchange=()=>showCreature().catch(e=>status(e.message));
  async function showCreature(){
    const c=selected();searchId=null;offset=null;
    el("manage-image-candidates").replaceChildren();el("manage-image-more").hidden=true;
    el("manage-current-image").replaceChildren();el("manage-image-history").replaceChildren();
    if(!c)return;
    el("manage-current-image").append(picture(c));
    const source=c.internet_image || c.profile?.image || {};
    el("manage-current-source").textContent=c.name+" · "+(source.original_source_url || "Source not recorded");
    const records=await request(`image-manager/${c.id}/history`);
    if(selected()?.id!==c.id)return;
    for(const record of records){
      const button=document.createElement("button");button.textContent=(record.active?"Current image · ":"Restore · ")+record.kind+" · "+(record.installed_on?new Date(record.installed_on).toLocaleString():"first recorded "+new Date(record.recorded_on).toLocaleString());
      button.disabled=record.active;button.onclick=async()=>{
        button.disabled=true;try{await request(`image-manager/${c.id}/restore`,{history_id:record.id});await refreshImages(c.id);}catch(e){status(e.message);button.disabled=false;}
      };el("manage-image-history").append(button);
    }
  }
  async function waitJob(job){
    let result=job;
    while(["pending","generating"].includes(result.status)){
      el("manage-image-status").textContent="Searching or preparing images… You can return to your adventure.";
      await new Promise(resolve=>setTimeout(resolve,700));result=await request("image-manager/jobs/"+job.job_id);
    }
    if(result.status!=="ready")throw Error(result.error||"Image search failed; the current image is safe.");
    return result;
  }
  async function displayCandidates(start=0){
    const c=selected();const page=await request(`image-manager/${c.id}/candidates/${searchId}?offset=${start}`);
    offset=page.next_offset;el("manage-image-more").hidden=offset===null;
    for(const candidate of page.candidates){
      const card=document.createElement("article"),image=document.createElement("img"),caption=document.createElement("p"),button=document.createElement("button");
      image.src=candidate.preview_url;image.alt=candidate.title||"Replacement candidate";image.loading="lazy";
      image.onerror=()=>{image.onerror=null;image.src="/static/assets/dinosaur.svg";};
      caption.textContent=(candidate.title||"Candidate")+" · "+(candidate.creator||"Creator not provided")+" · "+(candidate.license||"License unknown");
      button.textContent="Use this image";button.onclick=async()=>{
        button.disabled=true;try{await waitJob(await request(`image-manager/${c.id}/replace`,{candidate_id:candidate.id}));await refreshImages(c.id);el("manage-image-status").textContent="Image installed. The previous image is in history.";}catch(e){status(e.message);button.disabled=false;}
      };card.append(image,caption,button);el("manage-image-candidates").append(card);
    }
    el("manage-image-status").textContent=page.total?`${page.total} candidates found. Compare pictures, then select one.`:"No suitable candidates found. The current image is preserved.";
  }
  async function search(refresh=false,scientific=false){
    const c=selected();if(!c)throw Error("Choose a creature first.");
    const cid=c.id;
    const job=await request(`image-manager/${cid}/search`,{query:scientific?c.scientific_name:el("manage-image-query").value,refresh});
    const result=await waitJob(job);
    if(selected()?.id!==cid)return;
    searchId=job.job_id;el("manage-image-candidates").replaceChildren();await displayCandidates();
    if(result.diagnostics?.length)el("manage-image-status").textContent+=" "+result.diagnostics.join("; ");
  }
  action("manage-image-search",()=>search());action("manage-scientific-search",()=>search(false,true));action("manage-image-refresh",()=>search(true));
  action("manage-image-more",async()=>{const start=offset;await waitJob(await request("image-manager/more",{search_id:searchId,offset:start}));await displayCandidates(start);});
  async function refreshImages(cid){
    creatures=await api("/api/creatures");el("manage-creature").value=String(cid);
    await window.refreshCreatureLibrary?.();
    if(current?.id){current=await api("/api/story/tournaments/"+current.id);save();renderBracket();}
    await showCreature();
  }
  el("grownup-controls").addEventListener("focusin",()=>{if(!csrf)refreshSession().catch(e=>status(e.message));},{once:true});
  // Session tokens remain only in memory; never store passphrases or cookies in localStorage.
  refreshSession().catch(()=>status("Grown-up controls are temporarily unavailable."));
})();
