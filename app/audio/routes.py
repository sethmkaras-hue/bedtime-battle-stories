from typing import Literal
from pathlib import Path
import os
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .service import AudioService, QueueFull

router = APIRouter(prefix='/api/audio')
ROOT = Path(__file__).resolve().parents[2]


def create_service():
    return AudioService(os.environ.get('BBS_AUDIO_CACHE', ROOT / 'data/audio_cache'),
                        os.environ.get('BBS_MODEL_DIR', ROOT / 'data/models'))


class AudioRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['narration', 'pronunciation']
    provider: Literal['kokoro', 'piper', 'openai', 'browser']
    voice: str = Field(max_length=150)
    text: str = Field(min_length=1, max_length=6000)
    speed: float = Field(default=1, ge=.5, le=2)
    overrides: dict[str, str] = Field(default_factory=dict, max_length=8)

    @field_validator('overrides')
    @classmethod
    def bounded_overrides(cls, value):
        if any(not key or len(key) > 100 or len(replacement) > 200 for key, replacement in value.items()):
            raise ValueError('Pronunciation overrides are too long')
        return value


def submit(service, body):
    try:
        return service.submit(body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except QueueFull as error:
        raise HTTPException(429, str(error)) from error


@router.get('/providers')
def providers(request: Request):
    return request.app.state.audio.provider_info()


@router.post('')
def generate(body: AudioRequest, request: Request):
    return submit(request.app.state.audio, body.model_dump())


@router.get('/jobs/{key}')
def status(key: str, request: Request):
    validate_key(key)
    result = request.app.state.audio.status(key)
    if result is None:
        raise HTTPException(404, 'Audio job not found')
    return result


def validate_key(key):
    import re
    if re.fullmatch('[0-9a-f]{64}', key) is None:
        raise HTTPException(404, 'Audio not found')


@router.get('/files/{kind}/{key}')
def file(kind: Literal['narration', 'pronunciation'], key: str, request: Request):
    validate_key(key)
    service = request.app.state.audio
    path, _ = service._paths(kind, key)
    if service._ready(kind, key) is None:
        raise HTTPException(404, 'Audio not found')
    return FileResponse(path, media_type='audio/wav', headers={'Cache-Control': 'private, max-age=31536000, immutable'})


@router.get('/cache')
def cache_stats(request: Request):
    return request.app.state.audio.stats()


@router.delete('/cache')
def clear_cache(request: Request, x_bedtime_confirm: str = Header(default='')):
    if x_bedtime_confirm != 'clear':
        raise HTTPException(400, 'Cache deletion requires explicit confirmation')
    try:
        return request.app.state.audio.clear()
    except QueueFull as error:
        raise HTTPException(409, str(error)) from error


class BenchmarkRequest(BaseModel):
    provider: Literal['kokoro', 'piper']
    voice: str = Field(max_length=150)


@router.post('/benchmark')
def benchmark(body: BenchmarkRequest, request: Request):
    return submit(request.app.state.audio, {'kind': 'narration', 'provider': body.provider,
                  'voice': body.voice, 'text': 'The stars are shining. A little adventure begins beneath the moon. Everyone is safe, and the world is settling down to sleep.',
                  'speed': 1, 'overrides': {}})
