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
