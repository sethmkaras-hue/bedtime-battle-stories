import concurrent.futures
import json
from pathlib import Path
import sys
import threading
import time
import types
import wave
import pytest
from fastapi.testclient import TestClient
from app.audio.service import AudioService, QueueFull
from app.audio import providers
from app import main


def wav_file(path):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
        f.writeframes(b'\x00\x00' * 800)


class FakeProvider:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
    def is_available(self): return True
    def version(self): return 'test-v1'
    def list_voices(self): return [{'id':'test','name':'Test'}]
    def get_provider_info(self): return {'available':True,'voices':self.list_voices()}
    def generate_audio(self,text,voice,speed,destination):
        self.calls += 1; self.started.set(); self.release.wait(5)
        destination.write_bytes(b'partial')
        if self.fail: raise RuntimeError('test failure')
        wav_file(destination)


@pytest.fixture
def service(tmp_path):
    p=FakeProvider()
    s=AudioService(tmp_path/'cache',tmp_path/'models',providers={'kokoro':p})
    yield s,p
    p.release.set();s.close()


def request(**overrides):
    return dict(kind='narration',provider='kokoro',voice='test',text='Good night.',speed=1,overrides={})|overrides


def wait(s,key):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        result=s.status(key)
        if result['state'] not in ['queued','generating']:return result
        time.sleep(.01)
    pytest.fail('Audio job did not finish')


def test_cache_miss_hit_and_restart(service,tmp_path):
    s,p=service
    job=wait(s,s.submit(request())['key'])
    assert job['state']=='ready' and p.calls==1
    assert s.submit(request())['cached'] and p.calls==1
    restarted=AudioService(s.root,tmp_path/'models',providers={'kokoro':p})
    try:
        assert restarted.submit(request())['cached']
        assert p.calls==1
    finally:restarted.close()


def test_duplicate_concurrent_requests(service):
    s,p=service;p.release.clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:s.submit(request()),range(8)))
    assert len({r['key'] for r in results})==1
    p.release.set()
    assert wait(s,results[0]['key'])['state']=='ready' and p.calls==1


def test_cache_keys_cover_inputs(service):
    s,p=service
    base=s.submit(request())['key']
    for change in [{'text':'Another story.'},{'speed':.8},{'overrides':{'night':'nite'}},{'kind':'pronunciation'}]:
        assert s.submit(request(**change))['key']!=base
    p.version=lambda:'test-v2'
    assert s.submit(request())['key']!=base


def test_failure_cleanup_retry_and_clear(service):
    s,p=service;p.fail=True
    result=wait(s,s.submit(request())['key'])
    assert result['state']=='failed'
    assert not list(s.root.rglob('*.part'))
    assert s.stats()['count']==0
    p.fail=False
    assert wait(s,s.submit(request())['key'])['state']=='ready'
    assert s.stats()['count']==1
    assert s.clear()=={'count':0,'bytes':0}


def test_bounded_queue_and_clear_guard(tmp_path):
    p=FakeProvider();p.release.clear()
    s=AudioService(tmp_path/'cache',tmp_path/'models',providers={'kokoro':p},max_pending=1)
    try:
        s.submit(request());assert p.started.wait(2)
        s.submit(request(text='Second'))
        with pytest.raises(QueueFull):s.submit(request(text='Third'))
        with pytest.raises(QueueFull):s.clear()
    finally:p.release.set();s.close()


def test_missing_models_and_credentials(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('BBS_ENABLE_OPENAI',raising=False)
    for provider in [providers.KokoroProvider,providers.PiperProvider,providers.OpenAIProvider]:
        assert not provider(tmp_path).is_available()
    s=AudioService(tmp_path/'cache',tmp_path/'models')
    try:
        assert s.submit(request(provider='piper',voice='en_US-lessac-medium'))['fallback']
        assert s.submit(request(provider='openai',voice='coral'))['fallback']
        assert s.submit(request(provider='browser'))['fallback']
        assert s.stats()['count']==0
    finally:s.close()


def test_audio_api_and_path_validation(tmp_path,monkeypatch,service):
    s,p=service
    monkeypatch.setattr(main,'create_service',lambda:s)
    monkeypatch.setattr(main,'DB',tmp_path/'creatures.sqlite3')
    monkeypatch.setattr(main,'CATALOG',False)
    monkeypatch.setattr(main,'SAMPLE',False)
    with TestClient(main.app) as c:
        assert c.get('/api/audio/providers').json()['providers']['browser']['frontend_only']
        response=c.post('/api/audio',json=request());assert response.status_code==200
        ready=wait(s,response.json()['key'])
        assert c.get(ready['url']).headers['content-type']=='audio/wav'
        assert c.get('/api/audio/jobs/not-a-key').status_code==404
        assert c.get('/api/audio/files/narration/not-a-key').status_code==404
        assert c.delete('/api/audio/cache').status_code==400
        assert c.post('/api/audio',json=request(text='x'*6001)).status_code==422
        assert c.post('/api/audio',json=request(voice='invalid')).status_code==422
        assert c.delete('/api/audio/cache',headers={'X-Bedtime-Confirm':'clear'}).json()['count']==0


def test_kokoro_provider_cpu_adapter(tmp_path,monkeypatch):
    calls={}
    class Engine:
        @staticmethod
        def from_session(session,voices):calls['session']=session;return Engine()
        def get_voices(self):return ['af_heart']
        def create(self,text,**kwargs):calls.update(kwargs);return [0],24000
    monkeypatch.setitem(sys.modules,'kokoro_onnx',types.SimpleNamespace(Kokoro=Engine))
    monkeypatch.setitem(sys.modules,'soundfile',types.SimpleNamespace(write=lambda path,*a,**k:wav_file(path)))
    monkeypatch.setattr(providers,'cpu_session',lambda path:'cpu-session')
    p=providers.KokoroProvider(tmp_path);p.generate_audio('Hello','af_heart',.9,tmp_path/'test.wav')
    assert calls['session']=='cpu-session' and calls['speed']==.9
    assert (tmp_path/'test.wav').exists()


def test_piper_provider_cpu_adapter(tmp_path,monkeypatch):
    calls={}
    class Engine:
        def __init__(self,**kwargs):calls.update(kwargs)
        def synthesize_wav(self,text,output,syn_config):
            calls['scale']=syn_config.length_scale
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(8000);output.writeframes(b'\0\0'*10)
    class Config:
        @staticmethod
        def from_dict(value):return value
    monkeypatch.setitem(sys.modules,'piper',types.SimpleNamespace(PiperVoice=Engine,SynthesisConfig=lambda **kw:types.SimpleNamespace(**kw)))
    monkeypatch.setitem(sys.modules,'piper.config',types.SimpleNamespace(PiperConfig=Config))
    monkeypatch.setattr(providers,'cpu_session',lambda path:'cpu-session')
    p=providers.PiperProvider(tmp_path)
    model,config=p.model_files();config.parent.mkdir(parents=True);config.write_text('{}')
    p.generate_audio('Tyrannosaurus','en_US-lessac-medium',.8,tmp_path/'test.wav')
    assert calls['session']=='cpu-session' and calls['scale']==1.25


def test_openai_provider_uses_sdk_mock_without_paid_calls(tmp_path,monkeypatch):
    calls={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream_to_file(self,path):wav_file(path)
    class Client:
        def __init__(self,**kwargs):self.audio=types.SimpleNamespace(speech=types.SimpleNamespace(with_streaming_response=self))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def create(self,**kwargs):calls.update(kwargs);return Response()
    monkeypatch.setitem(sys.modules,'openai',types.SimpleNamespace(OpenAI=Client))
    monkeypatch.setenv('BBS_ENABLE_OPENAI','1');monkeypatch.setenv('OPENAI_API_KEY','mock-only')
    monkeypatch.setattr(providers,'installed',lambda name:True)
    p=providers.OpenAIProvider(tmp_path)
    p.generate_audio('Good night','coral',1,tmp_path/'test.wav')
    assert calls['response_format']=='wav' and calls['voice']=='coral'
