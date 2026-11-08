"""Optional CPU providers. Import heavy runtimes lazily in the audio worker."""
from abc import ABC, abstractmethod
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import wave


def installed(name):
    return importlib.util.find_spec(name) is not None


def cpu_session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, int(os.environ.get('BBS_TTS_THREADS', '2'))))
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])


class TTSProvider(ABC):
    name = ''
    voices = []
    package = ''

    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self.engine = None
        self._fingerprints = {}

    def model_files(self):
        return []

    def is_available(self):
        return installed(self.package) and all(p.is_file() for p in self.model_files())

    def list_voices(self):
        return [{'id': v, 'name': label} for v, label in self.voices]

    def version(self):
        from importlib.metadata import version
        digest = hashlib.sha256()
        digest.update((self.name + ':' + version(self.package.replace('_', '-'))).encode())
        for path in self.model_files():
            stat = path.stat()
            identity = (str(path), stat.st_size, stat.st_mtime_ns)
            if identity not in self._fingerprints:
                with path.open('rb') as stream:
                    self._fingerprints[identity] = hashlib.file_digest(stream, 'sha256').hexdigest()
            digest.update(self._fingerprints[identity].encode())
        return digest.hexdigest()

    def get_provider_info(self):
        available = self.is_available()
        return {'available': available, 'voices': self.list_voices(), 'cpu_only': True,
                'reason': '' if available else 'Install optional audio packages and download local models.'}

    @abstractmethod
    def generate_audio(self, text, voice, speed, destination):
        """Write a complete WAV to destination, or raise. Never publish partial audio."""


class KokoroProvider(TTSProvider):
    name = 'kokoro'
    package = 'kokoro_onnx'
    voices = [('af_heart', 'Heart · warm US English'), ('af_sarah', 'Sarah · US English'),
              ('bf_emma', 'Emma · UK English'), ('am_michael', 'Michael · US English'),
              ('bm_george', 'George · UK English')]

    def model_files(self):
        return [self.model_dir / 'kokoro/kokoro-v1.0.onnx', self.model_dir / 'kokoro/voices-v1.0.bin']

    def generate_audio(self, text, voice, speed, destination):
        import soundfile as sf
        from kokoro_onnx import Kokoro
        if self.engine is None:
            model, voices = self.model_files()
            self.engine = Kokoro.from_session(cpu_session(model), str(voices))
        if voice not in self.engine.get_voices():
            raise ValueError('Unknown Kokoro voice')
        samples, rate = self.engine.create(text, voice=voice, speed=speed,
                                          lang='en-gb' if voice.startswith('b') else 'en-us')
        sf.write(str(destination), samples, rate, format='WAV', subtype='PCM_16')


class PiperProvider(TTSProvider):
    name = 'piper'
    package = 'piper'
    voices = [('en_US-lessac-medium', 'Lessac · clear US English')]

    def model_files(self):
        base = self.model_dir / 'piper/en_US-lessac-medium.onnx'
        return [base, Path(str(base) + '.json')]

    def version(self):
        # Distribution is called piper-tts; import namespace is piper.
        import importlib.metadata
        digest = hashlib.sha256(importlib.metadata.version('piper-tts').encode())
        for path in self.model_files():
            stat = path.stat()
            identity = (str(path), stat.st_size, stat.st_mtime_ns)
            if identity not in self._fingerprints:
                with path.open('rb') as f:
                    self._fingerprints[identity] = hashlib.file_digest(f, 'sha256').hexdigest()
            digest.update(self._fingerprints[identity].encode())
        return digest.hexdigest()

    def generate_audio(self, text, voice, speed, destination):
        from piper import PiperVoice, SynthesisConfig
        from piper.config import PiperConfig
        if voice != self.voices[0][0]:
            raise ValueError('Unknown Piper voice')
        if self.engine is None:
            model, config = self.model_files()
            self.engine = PiperVoice(session=cpu_session(model), config=PiperConfig.from_dict(json.loads(config.read_text())))
        with wave.open(str(destination), 'wb') as output:
            self.engine.synthesize_wav(text, output, syn_config=SynthesisConfig(length_scale=1 / speed))


class OpenAIProvider(TTSProvider):
    name = 'openai'
    package = 'openai'
    voices = [(v, v.capitalize()) for v in ['coral', 'alloy', 'ash', 'ballad', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer']]

    def is_available(self):
        return os.environ.get('BBS_ENABLE_OPENAI') == '1' and bool(os.environ.get('OPENAI_API_KEY')) and installed('openai')

    def version(self):
        return os.environ.get('BBS_OPENAI_MODEL', 'gpt-4o-mini-tts')

    def get_provider_info(self):
        return {'available': self.is_available(), 'voices': self.list_voices(), 'cpu_only': False,
                'reason': '' if self.is_available() else 'Optional paid provider is not enabled or configured.'}

    def generate_audio(self, text, voice, speed, destination):
        from openai import OpenAI
        if not self.is_available():
            raise ValueError('Premium audio is disabled')
        with OpenAI(timeout=90, max_retries=0) as client:
            with client.audio.speech.with_streaming_response.create(
                model=self.version(), voice=voice, input=text, response_format='wav', speed=speed,
            ) as response:
                response.stream_to_file(destination)


class BrowserProvider:
    def get_provider_info(self):
        return {'available': True, 'frontend_only': True, 'voices': [],
                'reason': 'Device voices are discovered in the browser.'}
