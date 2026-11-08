"""Version 2 mobile browser integration. Run against a default-catalog server."""
import os
import sys
from playwright.sync_api import sync_playwright

SPEECH_STUB = '''
window.SpeechSynthesisUtterance=class{constructor(text){this.text=text;}};
Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{
 speaking:false,paused:false,last:null,spoken:[],getVoices(){return[]},addEventListener(){},
 speak(u){this.last=u;this.spoken.push(u.text);this.speaking=true},
 cancel(){this.speaking=false;this.paused=false;this.last=null},
 pause(){this.paused=true},resume(){this.paused=false}
}});
'''
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    page.add_init_script(SPEECH_STUB)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8502')
    page.locator('[data-category=dinosaur]').click()
    page.locator('.creature').nth(99).wait_for()
    page.locator('#search').fill('tyrannosaurus')
    assert page.locator('.creature').count()==1
    page.locator('.creature button').nth(1).click()
    assert page.evaluate('speechSynthesis.last.text')=='tie ran oh sore us'
    assert page.evaluate('speechSynthesis.last.rate')==0.8
    page.locator('.creature summary').click()
    assert 'Measurements: not yet verified' in page.locator('.creature').inner_text()
    page.locator('#search').fill('')
    page.locator('#random').click()
    page.wait_for_function("document.getElementById('count').textContent==='8 of 8 selected'")
    page.locator('#next').click()
    page.locator('#shuffle').check()
    page.locator('#start').click()
    page.locator('#bracket').wait_for(state='visible')
    assert page.locator('#rounds article').count()==7
    page.locator('#story').click()
    assert 'winner' not in page.locator('#chapter-text').inner_text().lower()
    page.locator('#play').click()
    page.locator('#pause').click()
    assert page.evaluate('speechSynthesis.paused')
    page.locator('#pause').click()
    assert not page.evaluate('speechSynthesis.paused')
    page.evaluate('lastAction=Date.now()-300001;checkIdle()')
    assert page.locator('#player').is_visible()
    # Complete speech chunks; narration completion must advance exactly once.
    page.evaluate('''()=>{let safety=0;while(speechSynthesis.speaking&&safety++<20){const u=speechSynthesis.last;speechSynthesis.speaking=false;u.onend();}}''')
    page.locator('#bracket').wait_for(state='visible')
    assert page.evaluate('current.completed')==1
    page.reload()
    page.locator('#bracket').wait_for(state='visible')
    assert page.evaluate('current.completed')==1
    for completed in range(2,8):
        page.locator('#story').click()
        page.locator('#finish').click()
        page.wait_for_function('(n)=>current.completed===n',arg=completed)
        assert page.locator('#bracket').is_visible()
    assert 'Our champion is' in page.locator('#champion').inner_text()
    assert page.locator('#story').is_hidden()
    assert page.locator('#rounds article').count()==7
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#home').click()
    page.locator('[data-category=ocean]').click()
    page.locator('.creature').nth(53).wait_for()
    page.locator('#random').click()
    page.wait_for_function("document.getElementById('count').textContent==='8 of 8 selected'")
    page.evaluate('lastAction=Date.now()-300001;checkIdle()')
    assert page.locator('#quiet').is_visible()
    page.locator('#resume').click()
    assert page.locator('#selection').is_visible()
    assert not errors,errors
    browser.close()
print('V2 mobile integration passed: catalog, pronunciation adapter, speech controls, seven chapters, advancement, reload, champion, ocean mix, idle mode')
