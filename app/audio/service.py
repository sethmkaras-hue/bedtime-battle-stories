"""Single bounded CPU worker, deterministic disk cache, no tournament storage."""
from collections import OrderedDict
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import queue
import threading
import time
import uuid
import wave
from .providers import KokoroProvider, PiperProvider, OpenAIProvider, BrowserProvider


class QueueFull(Exception):
    pass


class AudioService:
    def __init__(self, cache_dir, model_dir, providers=None, max_pending=8):
        self.root = Path(cache_dir)
        self.providers = providers if providers is not None else {p.name: p(model_dir) for p in [KokoroProvider, PiperProvider, OpenAIProvider]}
        self.jobs = OrderedDict()
        self.lock = threading.RLock()
        self.queue = queue.Queue(maxsize=max_pending)
        self.closed = False
        for kind in ['narration', 'pronunciation']:
            (self.root / kind).mkdir(parents=True, exist_ok=True)
        self.worker = threading.Thread(target=self._run, daemon=True, name='bedtime-audio')
        self.worker.start()

    def provider_info(self):
        result = {name: p.get_provider_info() for name, p in self.providers.items()}
        result['browser'] = BrowserProvider().get_provider_info()
        import platform
        return {'providers': result, 'runtime': {'python': platform.python_version(), 'implementation': platform.python_implementation()}}

    def _paths(self, kind, key):
        folder = self.root / kind
        return folder / (key + '.wav'), folder / (key + '.json')

    def _ready(self, kind, key, cached=True):
        path, metadata = self._paths(kind, key)
        if not path.is_file() or not metadata.is_file():
            return None
        try:
            metrics = json.loads(metadata.read_text())
            return {'key': key, 'state': 'ready', 'cached': cached,
                    'url': f'/api/audio/files/{kind}/{key}', 'metrics': metrics}
        except (OSError, ValueError):
            return None

    def submit(self, request):
        provider_name = request['provider']
        if provider_name == 'browser':
            return {'fallback': True, 'reason': 'Device speech selected'}
        provider = self.providers[provider_name]
        if not provider.is_available():
            # Never select a paid provider automatically. Try the other local
            # engine before falling back to browser speech.
            alternate = self.providers.get('piper' if provider_name == 'kokoro' else 'kokoro') if provider_name in {'kokoro', 'piper'} else None
            if alternate is not None and alternate.is_available():
                result = self.submit({**request, 'provider': alternate.name, 'voice': alternate.list_voices()[0]['id']})
                return {**result, 'fallback_from': provider_name}
            return {'fallback': True, 'reason': provider.get_provider_info()['reason']}
        if request['voice'] not in {v['id'] for v in provider.list_voices()}:
            raise ValueError('Choose an available voice for this provider')
        # Hashing/version lookup runs in FastAPI's sync threadpool, never its event loop.
        identity = {**request, 'model_version': provider.version(), 'cache_format': 1}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise QueueFull('Audio service is shutting down')
            ready = self._ready(request['kind'], key)
            if ready:
                return ready
            existing = self.jobs.get(key)
            if existing and existing['state'] in {'queued', 'generating'}:
                return dict(existing)
            job = {'key': key, 'kind': request['kind'], 'state': 'queued', 'cached': False}
            try:
                self.queue.put_nowait((key, dict(request)))
            except queue.Full:
                raise QueueFull('Story queue is full. Please try again shortly.')
            self.jobs[key] = job
            while len(self.jobs) > 128:
                old = next((k for k, j in self.jobs.items() if j['state'] in {'ready', 'failed'}), None)
                if old is None:
                    break
                self.jobs.pop(old)
            return dict(job)

    def status(self, key):
        with self.lock:
            if key in self.jobs:
                return dict(self.jobs[key])
        for kind in ['narration', 'pronunciation']:
            ready = self._ready(kind, key)
            if ready:
                return ready
        return None

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            key, request = item
            with self.lock:
                self.jobs[key]['state'] = 'generating'
            path, metadata = self._paths(request['kind'], key)
            temporary = path.with_name(key + '.' + uuid.uuid4().hex + '.part')
            temp_metadata = temporary.with_suffix('.json.part')
            try:
                # Also deduplicate generation across processes sharing the same cache.
                with path.with_suffix('.lock').open('a') as file_lock:
                    fcntl.flock(file_lock, fcntl.LOCK_EX)
                    ready = self._ready(request['kind'], key)
                    if ready is None:
                        text = request['text']
                        for name, replacement in sorted(request.get('overrides', {}).items(), key=lambda pair: -len(pair[0])):
                            text = text.replace(name, replacement)
                        start = time.monotonic()
                        self.providers[request['provider']].generate_audio(text, request['voice'], request['speed'], temporary)
                        self.providers[request['provider']].last_error = ''
                        elapsed = time.monotonic() - start
                        with wave.open(str(temporary), 'rb') as wav:
                            duration = wav.getnframes() / wav.getframerate()
                        if duration <= 0 or temporary.stat().st_size < 44:
                            raise ValueError('Empty generated audio')
                        metrics = {'generation_seconds': round(elapsed, 3), 'audio_seconds': round(duration, 3),
                                   'real_time_factor': round(elapsed / duration, 3), 'provider': request['provider']}
                        temp_metadata.write_text(json.dumps(metrics))
                        temporary.replace(path)
                        temp_metadata.replace(metadata)
                        ready = self._ready(request['kind'], key, cached=False)
                with self.lock:
                    self.jobs[key] = ready
            except Exception as error:
                self.providers[request['provider']].last_error = f'Last generation failed ({type(error).__name__}). Check installed dependencies and model files; retry after correcting setup.'
                logging.getLogger(__name__).warning('Audio provider %s failed (%s)', request['provider'], type(error).__name__)
                with self.lock:
                    self.jobs[key] = {'key': key, 'state': 'failed', 'error': 'Audio generation failed. Check provider setup or choose a device voice.'}
            finally:
                temporary.unlink(missing_ok=True)
                temp_metadata.unlink(missing_ok=True)
                self.queue.task_done()

    def stats(self):
        files = [p for kind in ['narration', 'pronunciation'] for p in (self.root / kind).glob('*.wav')]
        all_files = [p for kind in ['narration', 'pronunciation'] for p in (self.root / kind).iterdir() if p.is_file()]
        size = 0
        for path in all_files:
            try:
                size += path.stat().st_size
            except FileNotFoundError:
                pass  # A completed temporary file may have just been renamed.
        return {'count': len(files), 'bytes': size}

    def clear(self):
        with self.lock:
            if any(j['state'] in {'queued', 'generating'} for j in self.jobs.values()):
                raise QueueFull('Wait for current audio generation to finish before clearing the cache.')
            # Only known cache extensions in known directories; never remove models/data.
            for kind in ['narration', 'pronunciation']:
                for pattern in ['*.wav', '*.json', '*.part']:
                    for path in (self.root / kind).glob(pattern):
                        path.unlink(missing_ok=True)
            self.jobs.clear()
        return self.stats()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            # Drop queued work on shutdown rather than blocking on a full queue.
            while True:
                try:
                    queued = self.queue.get_nowait()
                except queue.Empty:
                    break
                if queued is not None:
                    self.jobs[queued[0]] = {'key': queued[0], 'state': 'failed', 'error': 'Server restarted; please retry.'}
                self.queue.task_done()
        self.queue.put_nowait(None)
        self.worker.join(timeout=5)
