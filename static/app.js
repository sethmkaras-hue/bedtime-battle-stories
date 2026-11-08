'use strict';
let category='', library=[], selected=[], current=null, lastAction=Date.now(), screen='categories', beforeQuiet='categories';
const $=id=>document.getElementById(id);
const screens=['categories','selection','settings','bracket','player','quiet'];
function touch(){lastAction=Date.now();}
function show(id){screen=id;screens.forEach(s=>$(s).hidden=s!==id);$('back').hidden=['categories','quiet'].includes(id);$('message').textContent='';touch();}
function save(){try {sessionStorage.setItem('bedtimeTournament',JSON.stringify(current));} catch { /* Storage can be unavailable in private browsers. */ }}
function stopAudio(){window.speechSynthesis?.cancel();document.querySelectorAll('audio').forEach(a=>a.pause());}
function narrationActive(){return Boolean(window.speechSynthesis?.speaking && !window.speechSynthesis?.paused)||Array.from(document.querySelectorAll('audio')).some(a=>!a.paused&&!a.ended);}
function checkIdle(){if(narrationActive()){touch();return;}if(screen!=='quiet'&&Date.now()-lastAction>=300000){beforeQuiet=screen;stopAudio();show('quiet');}}
document.addEventListener('pointerdown',touch);document.addEventListener('keydown',touch);document.addEventListener('visibilitychange',checkIdle);setInterval(checkIdle,1000);
// Single pronunciation adapter, replaceable with verified audio in a later phase.
function say(text){if(!window.speechSynthesis||!window.SpeechSynthesisUtterance){$('message').textContent='Pronunciation is unavailable in this browser.';return;}stopAudio();touch();const u=new SpeechSynthesisUtterance(text);u.rate=.85;u.onend=touch;u.onerror=touch;window.speechSynthesis.speak(u);}
function hear(c){const b=document.createElement('button');b.textContent='Hear';b.setAttribute('aria-label','Pronounce '+c.name);b.onclick=()=>say(c.pronunciation||c.name);return b;}
async function api(path,options){const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Please check your selection and settings.');return data;}
function guarded(action){return async()=>{try {await action();}catch(e){$('message').textContent=e.message||'Please try again.';}};}
function render(){const term=$('search').value.toLocaleLowerCase();$('creatures').replaceChildren();library.filter(c=>(c.name+' '+c.scientific_name).toLocaleLowerCase().includes(term)).forEach(c=>{const el=document.createElement('div');el.className='creature';const b=document.createElement('button');const pos=selected.indexOf(c.id);b.textContent=(pos>=0?(pos+1)+'. ':'')+c.name;b.setAttribute('aria-pressed',String(pos>=0));b.disabled=selected.length===8&&pos<0;b.onclick=()=>{if(pos>=0)selected=selected.filter(x=>x!==c.id);else if(selected.length<8)selected.push(c.id);render();};el.append(b,hear(c));$('creatures').append(el);});$('count').textContent=selected.length+' of 8 selected';$('next').disabled=selected.length!==8;$('random').disabled=library.length<8;}
document.querySelectorAll('[data-category]').forEach(b=>b.onclick=guarded(async()=>{category=b.dataset.category;library=await api('/api/creatures?category='+encodeURIComponent(category));selected=[];$('search').value='';render();show('selection');if(library.length<8)$('message').textContent='This library needs at least eight creatures. Ask a parent to enable the development sample library.';}));
$('search').oninput=render;
$('random').onclick=guarded(async()=>{const data=await api('/api/selection/random?category='+encodeURIComponent(category));selected=data.creature_ids;render();});
$('next').onclick=()=>show('settings');
function renderBracket(){ $('rounds').replaceChildren();current.rounds.forEach(round=>{const h=document.createElement('h3');h.textContent=round.name;$('rounds').append(h);round.matches.forEach((m,i)=>{const a=document.createElement('article');const label=document.createElement('p');label.textContent='Match '+(i+1);a.append(label);['left','right'].forEach((side,n)=>{if(n)a.append(document.createTextNode(' versus '));const c=m[side];const span=document.createElement('span');span.textContent=c?c.name:'Winner of earlier match';a.append(span);if(c)a.append(hear(c));});$('rounds').append(a);});});}
$('start').onclick=guarded(async()=>{const next=await api('/api/tournament',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({creature_ids:selected,shuffle:$('shuffle').checked,realism:$('realism').value,duration:$('duration').value})});current=next;save();renderBracket();show('bracket');});
$('story').onclick=()=>{const m=current.rounds[0].matches[0];$('speak').textContent='Hear '+m.left.name+' and '+m.right.name;show('player');};
$('speak').onclick=()=>{if(current){const m=current.rounds[0].matches[0];say(m.left.name+' versus '+m.right.name);}};
$('stop').onclick=()=>{stopAudio();touch();};
$('home').onclick=()=>{stopAudio();show('categories');};
$('back').onclick=()=>{stopAudio();show({selection:'categories',settings:'selection',bracket:library.length?'settings':'categories',player:'bracket'}[screen]||'categories');};
$('resume').onclick=()=>show(beforeQuiet);
async function restore(){try {const config=await api('/api/config');$('sample').hidden=!config.sample_data;const stored=JSON.parse(sessionStorage.getItem('bedtimeTournament')||'null');if(stored){const ids=stored.rounds[0].matches.flatMap(m=>[m.left.id,m.right.id]);current=await api('/api/tournament',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({creature_ids:ids,realism:stored.realism,duration:stored.duration})});renderBracket();show('bracket');}}catch {try{sessionStorage.removeItem('bedtimeTournament');}catch{ /* optional storage */ }}}
restore();
