"""English G2P for Kokoro: never rely on a finite word lexicon.

Sherpa 2.x accepts Unicode IPA codepoints per sentence. Package imports stay
lazy; no model or Piper voice is needed for this phonemizer.
"""
import re
import threading

_espeak_lock = threading.Lock()


def phoneme_sentences(text, language, tokens):
    import espeakng_loader
    import phonemizer
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    vocabulary = {line.rsplit(' ', 1)[0] for line in tokens.read_text().splitlines()}
    batches = []
    with _espeak_lock:
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        for sentence in re.split(r'(?<=[.!?])\s+|\n+', text):
            if not sentence.strip():
                continue
            ipa = phonemizer.phonemize(sentence, language=language, backend='espeak',
                                      preserve_punctuation=True, with_stress=True, njobs=1)
            ipa = ''.join(char for char in ipa if char in vocabulary).strip()
            # The Kokoro style table supports at most 510 tokens. Split long
            # sentences at word boundaries instead of silently truncating them.
            while ipa:
                limit = ipa.rfind(' ', 0, 400) if len(ipa) > 400 else len(ipa)
                if limit <= 0:
                    limit = min(len(ipa), 400)
                batches.append([ord(char) for char in ipa[:limit]])
                ipa = ipa[limit:].lstrip()
    if not batches:
        raise ValueError('No speakable English phonemes were produced')
    return batches
