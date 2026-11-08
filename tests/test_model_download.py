import hashlib
import httpx
import pytest
from scripts.setup_audio import download


def test_model_download_verifies_and_reuses_existing_file(tmp_path):
    content=b'model bytes from trusted test transport'
    digest=hashlib.sha256(content).hexdigest()
    calls=[]
    def respond(request):
        calls.append(request.url)
        return httpx.Response(200,content=content)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        target=tmp_path/'model.onnx'
        download(client,'https://example.test/model',target,digest)
        download(client,'https://example.test/model',target,digest)
        assert target.read_bytes()==content and len(calls)==1
        assert not list(tmp_path.glob('*.part'))


def test_model_checksum_failure_keeps_no_partial_artifact(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'bad'))) as client:
        target=tmp_path/'model.onnx'
        with pytest.raises(RuntimeError):download(client,'https://example.test/model',target,'0'*64)
        assert not target.exists()
        assert not list(tmp_path.glob('*.part'))


def test_sherpa_bundle_install_is_verified_safe_and_repeatable(tmp_path,monkeypatch):
    import io
    import tarfile
    from scripts import setup_audio
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:bz2') as archive:
        for name in setup_audio.KOKORO_MEMBERS | {'../../escape.txt'}:
            data=b'fixture data'
            member=tarfile.TarInfo('kokoro-multi-lang-v1_0/'+name);member.size=len(data)
            archive.addfile(member,io.BytesIO(data))
    content=buffer.getvalue()
    monkeypatch.setattr(setup_audio,'KOKORO_SHA256',hashlib.sha256(content).hexdigest())
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=content))) as client:
        setup_audio.install_kokoro(client,tmp_path/'models')
        setup_audio.install_kokoro(client,tmp_path/'models')
    assert (tmp_path/'models/kokoro-sherpa/tokens.txt').exists()
    assert not (tmp_path/'escape.txt').exists()
    assert not list((tmp_path/'models').glob('.kokoro-setup-*'))


def test_all_setup_continues_after_one_provider_fails(tmp_path,monkeypatch):
    from scripts import setup_audio
    called=[]
    monkeypatch.setattr('sys.argv',['setup_audio.py','all','--model-dir',str(tmp_path)])
    def fail(*args):raise RuntimeError('network test failure')
    monkeypatch.setattr(setup_audio,'install_kokoro',fail)
    monkeypatch.setattr(setup_audio,'install_piper',lambda *args:called.append('piper'))
    assert setup_audio.main()==1
    assert called==['piper']
