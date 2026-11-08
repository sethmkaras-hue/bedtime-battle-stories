"""Run against a sample-data server: python tests/mobile_smoke.py [base URL]."""
import os
import sys
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True)
    errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8502')
    page.locator('#sample').wait_for(state='visible')
    page.locator('[data-category=dinosaur]').click()
    page.locator('.creature').nth(7).wait_for()
    page.locator('#search').fill('tyranno')
    assert page.locator('.creature').count()==1
    page.locator('#search').fill('')
    for i in range(8):
        page.locator('.creature').nth(i).locator('button').first.click()
    assert page.locator('#count').inner_text()=='8 of 8 selected'
    page.locator('#next').click()
    page.locator('#shuffle').check()
    page.locator('#realism').select_option('realistic')
    page.locator('#duration').select_option('long')
    page.locator('#start').click()
    page.locator('#bracket').wait_for(state='visible')
    assert page.locator('#rounds article').count()==7
    assert page.locator('#rounds button').count()==8
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.reload()
    page.locator('#bracket').wait_for(state='visible')
    page.locator('#story').click()
    page.locator('#player').wait_for(state='visible')
    # Deterministic clock and narration stub, without waiting five real minutes.
    page.evaluate("Object.defineProperty(window,'speechSynthesis',{configurable:true,value:{speaking:true,paused:false,cancel(){this.speaking=false}}}); lastAction=Date.now()-300001;checkIdle()")
    assert page.locator('#player').is_visible()
    page.evaluate('speechSynthesis.speaking=false;lastAction=Date.now()-300001;checkIdle()')
    assert page.locator('#quiet').is_visible()
    page.locator('#resume').click()
    assert page.locator('#player').is_visible()
    page.locator('#home').click()
    page.locator('[data-category=shark]').click()
    page.locator('#random').click()
    page.wait_for_function("document.getElementById('count').textContent==='8 of 8 selected'")
    assert not errors, errors
    browser.close()
print('Mobile Chromium smoke passed: selection, search, random, settings, bracket, reload, player, timeout, layout')
