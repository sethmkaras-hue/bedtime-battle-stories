let category="", library=[], selected=[], current=null, lastAction=Date.now();
const $=id=>document.getElementById(id);
function show(id){["categories","selection","settings","bracket","player"].forEach(s=>$(s).hidden=s!==id);touch()}
function touch(){lastAction=Date.now();$("timeout").textContent=""}
document.addEventListener("pointerdown",touch);
document.addEventListener("keydown",touch);
setInterval(()=>{if(!$("player").hidden&&Date.now()-lastAction>=300000){speechSynthesis.cancel();$("timeout").textContent="Bedtime mode: playback stopped after five minutes.";lastAction=Date.now()}},1000);
function say(text){speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(text);utterance.rate=.85;speechSynthesis.speak(utterance)}
function render(){const term=$("search").value.toLowerCase();$("creatures").replaceChildren();library.filter(c=>c.name.toLowerCase().includes(term)).forEach(c=>{const el=document.createElement("div");el.className="creature";const b=document.createElement("button");b.textContent=(selected.includes(c.id)?"✓ ":"")+c.name;b.onclick=()=>{if(selected.includes(c.id))selected=selected.filter(x=>x!==c.id);else if(selected.length<8)selected.push(c.id);render()};const p=document.createElement("button");p.textContent="Hear";p.setAttribute("aria-label","Pronounce "+c.name);p.onclick=()=>say(c.pronunciation||c.name);el.append(b,p);$("creatures").append(el)});$("count").textContent=selected.length+" of 8 selected";$("next").disabled=selected.length!==8}
document.querySelectorAll("[data-category]").forEach(b=>b.onclick=async()=>{category=b.dataset.category;const response=await fetch("/api/creatures?category="+encodeURIComponent(category));library=await response.json();selected=[];$("search").value="";render();show("selection");$("message").textContent=library.length<8?"Creature library will be populated in Phase 2.":""});
$("search").oninput=render;
$("random").onclick=()=>{selected=library.map(c=>c.id).sort(()=>Math.random()-.5).slice(0,8);render()};
$("next").onclick=()=>show("settings");
$("start").onclick=async()=>{const response=await fetch("/api/tournament",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({creature_ids:selected,shuffle:$("shuffle").checked,realism:$("realism").value,duration:$("duration").value})});const data=await response.json();if(!response.ok){$("message").textContent=data.detail;return}current=data;$("rounds").replaceChildren();data.rounds.forEach(round=>{const h=document.createElement("h3");h.textContent=round.name;$("rounds").append(h);round.matches.forEach(m=>{const a=document.createElement("article");a.textContent=(m.left?.name||"TBD")+" vs "+(m.right?.name||"TBD");$("rounds").append(a)})});show("bracket")};
$("story").onclick=()=>show("player");
$("speak").onclick=()=>{if(current)say(current.rounds[0].matches[0].left.name+" versus "+current.rounds[0].matches[0].right.name)};
$("stop").onclick=()=>speechSynthesis.cancel();
