"""Mobile UX regression with deterministic audio transport; no models or paid calls."""
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import wave
from playwright.sync_api import sync_playwright


def run(base='http://127.0.0.1:8502', screenshots=None):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0\0'*64000)
    wav=buffer.getvalue()
    state={'polls':0,'deletes':0,'requests':0}
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script('''window.SpeechSynthesisUtterance=class{constructor(t){this.text=t}};Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{speaking:false,paused:false,last:null,getVoices(){return[]},addEventListener(){},speak(u){this.last=u;this.speaking=true},cancel(){this.speaking=false;this.paused=false},pause(){this.paused=true},resume(){this.paused=false}}});''')
        def route_audio(route):
            path=urlsplit(route.request.url).path
            if path.endswith('/providers'):
                data={'providers':{'kokoro':{'available':True,'voices':[{'id':'af_heart','name':'Heart'},{'id':'af_sarah','name':'Sarah'}]},'piper':{'available':False,'reason':'Test missing models','voices':[{'id':'en_US-lessac-medium','name':'Lessac'}]},'browser':{'available':True,'voices':[]},'openai':{'available':False,'voices':[]}}}
            elif path.endswith('/cache'):
                if route.request.method=='DELETE':state['deletes']+=1
                data={'count':0 if state['deletes'] else 2,'bytes':2048}
            elif '/files/' in path:
                route.fulfill(status=200,content_type='audio/wav',body=wav);return
            elif '/jobs/' in path:
                state['polls']+=1
                data={'key':'a'*64,'state':'ready' if state['polls']>=2 else 'generating','url':'/api/audio/files/narration/'+'a'*64,'metrics':{'generation_seconds':.1,'audio_seconds':8,'real_time_factor':.0125}}
            else:
                state['requests']+=1;state['polls']=0
                body=route.request.post_data_json
                data={'fallback':True} if body.get('provider') in ['piper','browser'] else {'key':'a'*64,'state':'queued'}
            route.fulfill(status=200,json=data)
        page.route('**/api/audio**',route_audio)
        # Preserve coverage of the original session-only client/API contract.
        # Dedicated chapters_smoke.py exercises the new persistent flow.
        def legacy_tournament(route):
            if route.request.method != 'POST':return route.continue_()
            body=route.request.post_data_json
            response=route.fetch(url=base+'/api/tournament',method='POST',post_data=json.dumps({'creature_ids':body['creature_ids'],'shuffle':body.get('shuffle',False)}))
            route.fulfill(response=response)
        page.route('**/api/story/tournaments',legacy_tournament)
        def shot(name):
            if screenshots:
                Path(screenshots).mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(Path(screenshots)/(name+'.png')),full_page=True)
        page.goto(base);page.locator('#welcome').wait_for(state='visible');shot('home-mobile')
        page.locator('#settings-open').click()
        assert page.locator('#duration').input_value()=='normal'
        assert page.locator('#realism').input_value()=='balanced'
        page.locator('#idle-minutes').select_option('2')
        page.locator('#narration-voice').select_option('af_sarah')
        page.locator('#reduced-motion').check()
        page.locator('#timeout-enabled').uncheck()
        page.evaluate('lastAction=Date.now()-900001;checkIdle()')
        assert page.locator('#settings').is_visible()
        page.locator('#timeout-enabled').check()
        page.locator('#pronunciation-buttons').uncheck()
        assert page.evaluate("document.body.classList.contains('hide-pronunciation')")
        page.locator('#pronunciation-buttons').check()
        page.locator('#clear-cache').click();assert state['deletes']==0
        page.locator('#confirm-clear').click();page.wait_for_function("document.getElementById('cache-confirm').hidden")
        assert state['deletes']==1
        page.reload();page.locator('#settings-open').click()
        assert page.locator('#narration-voice').input_value()=='af_sarah'
        assert page.locator('#idle-minutes').input_value()=='2'
        assert page.locator('#reduced-motion').is_checked()
        page.locator('#back').click();page.locator('#start-adventure').click()
        page.locator('[data-category=dinosaur]').click();page.locator('.creature').nth(7).wait_for()
        page.locator('#search').evaluate("e=>e.parentElement.open=true")
        page.locator('#search').fill('tyrannosaurus');assert page.locator('.creature').count()==1
        page.locator('.speaker').first.click()
        assert page.evaluate('speechSynthesis.last') is None
        assert 'not prepared' in page.locator('#message').inner_text()
        assert state['requests']==0
        page.locator('#search').fill('')
        page.locator('#creatures .creature-select').first.click()
        assert page.locator('#count').inner_text()=='1 of 8 Selected'
        page.locator('.selection-slot.filled').click()
        assert page.locator('#next').is_disabled()
        page.locator('#random').click();page.wait_for_function("selected.length===8")
        assert page.locator('.selection-slot.filled').count()==8
        shot('selection-mobile')
        page.locator('#next').click();page.locator('#bracket').wait_for(state='visible')
        assert page.locator('.match[data-match]').count()==7
        assert page.locator('.match.active').count()==1
        assert page.locator('.contender.winner').count()==0
        shot('bracket-mobile')
        page.locator('#settings-open').click()
        page.locator('#preview-story').click();page.wait_for_function('!audio.generating && !busy')
        page.locator('#story-audio').dispatch_event('ended')
        page.wait_for_timeout(150)
        assert page.evaluate('current.completed')==0 # Voice previews must not finish a battle.
        page.locator('#back').click()
        assert page.locator('#bracket').is_visible() and page.evaluate('current.completed')==0
        page.locator('#story').click();page.locator('#player').wait_for(state='visible')
        page.evaluate('lastAction=Date.now()-120001;checkIdle()')
        assert page.locator('#player').is_visible() # Generation defers quiet mode.
        page.wait_for_function('!audio.generating')
        assert page.evaluate("document.getElementById('story-audio').paused") # Autoplay is off by default.
        assert 'winner' not in page.locator('#chapter-text').inner_text().lower()
        page.locator('#play').click();page.wait_for_function("!document.getElementById('story-audio').paused")
        assert page.evaluate('current.completed')==0
        page.locator('#pause').click();assert page.evaluate("document.getElementById('story-audio').paused")
        saved_time=page.evaluate("document.getElementById('story-audio').currentTime")
        page.locator('#pause').click();page.wait_for_function("!document.getElementById('story-audio').paused")
        assert page.evaluate("document.getElementById('story-audio').currentTime")>=saved_time
        requests=state['requests'];page.locator('#replay').click();assert state['requests']==requests
        page.evaluate('lastAction=Date.now()-120001;checkIdle()');assert page.locator('#player').is_visible()
        shot('story-mobile')
        page.locator('#story-audio').dispatch_event('ended')
        page.wait_for_function('current.completed===1');assert page.locator('#bracket').is_visible()
        page.reload();page.locator('#continue-adventure').wait_for(state='visible');page.locator('#continue-adventure').click()
        assert page.evaluate('current.completed')==1
        for completed in range(2,8):
            page.locator('#story').click();page.locator('#finish').click()
            page.wait_for_function('(n)=>current.completed===n',arg=completed)
        assert page.locator('#celebration').is_visible()
        shot('champion-mobile')
        page.locator('#settings-open').click();assert page.evaluate('current.completed')==7
        page.locator('#back').click();assert page.locator('#celebration').is_visible()
        page.locator('#play-again').click();page.locator('#bracket').wait_for(state='visible')
        assert page.evaluate('current.completed')==0
        page.locator('#home').click();page.locator('#surprise').click();page.locator('#bracket').wait_for(state='visible')
        assert page.evaluate('current.entrant_ids.length')==8
        page.locator('#home').click();page.locator('#start-adventure').click();page.locator('[data-category=ocean]').click()
        page.locator('#random').click();page.wait_for_function('selected.length===8')
        page.evaluate('lastAction=Date.now()-120001;checkIdle()');assert page.locator('#quiet').is_visible()
        page.locator('#resume').click();assert page.locator('#selection').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.set_viewport_size({'width':1440,'height':1000});page.locator('#home').click();shot('home-desktop')
        assert not errors,errors
        browser.close()
    print('Redesign mobile integration passed: settings, selection, bracket, audio/cache controls, seven battles, celebration, surprise, quiet mode')

if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8502',sys.argv[2] if len(sys.argv)>2 else None)
