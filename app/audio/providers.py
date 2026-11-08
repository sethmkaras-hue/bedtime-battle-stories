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
        self.last_error = ''

    def model_files(self):
        return []

    def unavailable_reason(self):
        missing_packages = [name for name in getattr(self, 'dependencies', [self.package]) if not installed(name)]
        if missing_packages:
            return f'Missing dependencies: {", ".join(missing_packages)}. Install requirements-audio.txt with this app’s Python interpreter.'
        missing = [p.name for p in self.model_files() if not p.is_file()]
        if missing:
            return f'Missing model files: {", ".join(missing)}. Run scripts/setup_audio.py {self.name}; check download access if it fails.'
        return ''

    def is_available(self):
        return not self.unavailable_reason()

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
                'reason': self.unavailable_reason(), 'last_error': self.last_error}

    @abstractmethod
    def generate_audio(self, text, voice, speed, destination):
        """Write a complete WAV to destination, or raise. Never publish partial audio."""


class KokoroProvider(TTSProvider):
    name = 'kokoro'
    package = 'sherpa_onnx'
    dependencies = ['sherpa_onnx', 'phonemizer', 'espeakng_loader', 'soundfile']
    voices = [('af_heart', 'Heart · warm US English'), ('af_sarah', 'Sarah · US English'),
              ('bf_emma', 'Emma · UK English'), ('am_michael', 'Michael · US English'),
              ('bm_george', 'George · UK English')]
    # Official pinned Kokoro v1.0 Sherpa bundle speaker map. Names remain stable
    # for saved browser settings; cache identity includes the new model/runtime.
    speaker_ids = {'af_heart': 3, 'af_sarah': 9, 'bf_emma': 21, 'am_michael': 16, 'bm_george': 26}

    def model_files(self):
        root = self.model_dir / 'kokoro-sherpa'
        return [root / name for name in ['model.onnx', 'voices.bin', 'tokens.txt']]

    def version(self):
        from importlib.metadata import version
        return hashlib.sha256((super().version() + version('phonemizer') + version('espeakng-loader') + ':ipa-v1').encode()).hexdigest()

    def generate_audio(self, text, voice, speed, destination):
        import soundfile as sf
        import sherpa_onnx
        if voice not in self.speaker_ids:
            raise ValueError('Unknown Kokoro voice')
        language = 'gb' if voice.startswith('b') else 'us'
        if self.engine is None:
            model, voices, tokens = self.model_files()
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(model), voices=str(voices), tokens=str(tokens)),
                    provider='cpu', num_threads=max(1, min(4, int(os.environ.get('BBS_TTS_THREADS', '2'))))),
                max_num_sentences=1)
            if not config.validate():
                raise ValueError('Kokoro model configuration is invalid; rerun model setup')
            self.engine = sherpa_onnx.OfflineTts(config)

        generation = sherpa_onnx.GenerationConfig()
        generation.sid = self.speaker_ids[voice]
        generation.speed = speed
        from .phonemes import phoneme_sentences
        generation.phoneme_codepoints = phoneme_sentences(text, 'en-gb' if language == 'gb' else 'en-us', self.model_files()[2])
        audio = self.engine.generate(text, generation)
        sf.write(str(destination), audio.samples, audio.sample_rate, format='WAV', subtype='PCM_16')


class PiperProvider(TTSProvider):
    name = 'piper'
    package = 'piper'
    dependencies = ['piper', 'onnxruntime']
    voices = [('en_US-lessac-medium', 'Lessac · clear US English')]

    def model_files(self):
        base = self.model_dir / 'piper/en_US-lessac-medium.onnx'
        return [base, Path(str(base) + '.json')]

    def version(self):
        # Distribution is called piper-tts; import namespace is piper.
        import importlib.metadata
        digest = hashlib.sha256((importlib.metadata.version('piper-tts') + ':' + importlib.metadata.version('onnxruntime')).encode())
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
