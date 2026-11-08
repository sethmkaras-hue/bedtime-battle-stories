import os
from pathlib import Path
import subprocess
import sys
import types
from app.audio.phonemes import phoneme_sentences


def test_phonemizer_uses_ipa_for_unknown_words_and_preserves_long_sentences(tmp_path,monkeypatch):
    # No optional engine is needed by the ordinary test suite.
    ipa='bɪɡˈɪnz '*100
    monkeypatch.setitem(sys.modules,'espeakng_loader',types.SimpleNamespace(get_library_path=lambda:'test-lib',get_data_path=lambda:'test-data'))
    monkeypatch.setitem(sys.modules,'phonemizer',types.SimpleNamespace(phonemize=lambda *args,**kw:ipa))
    wrapper=types.SimpleNamespace(set_library=lambda x:None,set_data_path=lambda x:None)
    monkeypatch.setitem(sys.modules,'phonemizer.backend.espeak.wrapper',types.SimpleNamespace(EspeakWrapper=wrapper))
    tokens=tmp_path/'tokens.txt';tokens.write_text('\n'.join(f'{char} {i}' for i,char in enumerate(set(ipa))))
    batches=phoneme_sentences('An unknown creature begins its adventure.','en-us',tokens)
    assert len(batches)>1 and all(len(b)<=400 for b in batches)
    result=''.join(''.join(map(chr,b)) for b in batches)
    assert result.replace(' ','')==ipa.replace(' ','')


def test_launcher_rejects_mismatched_virtual_environment(tmp_path):
    binary=tmp_path/'env/bin/python';binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\necho 99.0\n');binary.chmod(0o755)
    root=Path(__file__).resolve().parents[1]
    run=subprocess.run(['bash',str(root/'START_APP.sh')],env={**os.environ,'BBS_PYTHON':sys.executable,'BBS_VENV':str(binary.parents[1])},capture_output=True,text=True,timeout=10)
    assert run.returncode==1 and 'Python mismatch' in run.stderr


def test_launcher_reports_broken_environment(tmp_path):
    root=Path(__file__).resolve().parents[1]
    run=subprocess.run(['bash',str(root/'START_APP.sh')],env={**os.environ,'BBS_PYTHON':sys.executable,'BBS_VENV':str(tmp_path)},capture_output=True,text=True,timeout=10)
    assert run.returncode==1 and 'virtual environment is broken' in run.stderr
