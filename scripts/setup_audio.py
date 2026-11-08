#!/usr/bin/env python3
"""Explicit, checksum-verified downloads. Never called by application startup."""
import argparse
import hashlib
import json
import sys
import tarfile
import tempfile
import os
from pathlib import Path
import httpx

KOKORO_ARCHIVE = 'kokoro-multi-lang-v1_0.tar.bz2'
KOKORO_SHA256 = '60703707bc05ccd48d60e1eb723f38b07d6e474795a0b6a588d7220400e0f7a4'
KOKORO_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/'
KOKORO_MEMBERS = {'model.onnx', 'voices.bin', 'tokens.txt', 'LICENSE', 'README.md'}
PIPER_URL = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/'


def download(client, url, target, expected, algorithm='sha256', expected_size=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with target.open('rb') as f:
            if hashlib.file_digest(f, algorithm).hexdigest() == expected:
                print('Already verified:', target.name)
                return
        raise RuntimeError(f'{target.name} exists but has a different checksum. Preserve or remove it before retrying.')
    temporary = target.with_name(target.name + '.part')
    digest = hashlib.new(algorithm)
    try:
        with client.stream('GET', url) as response:
            response.raise_for_status()
            with temporary.open('wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk);digest.update(chunk)
        if digest.hexdigest() != expected or (expected_size is not None and temporary.stat().st_size != expected_size):
            raise RuntimeError(f'Checksum/size verification failed for {target.name}')
        temporary.replace(target)
        print('Downloaded and verified:', target.name)
    finally:
        temporary.unlink(missing_ok=True)


def install_kokoro(client, model_dir):
    destination = model_dir / 'kokoro-sherpa'
    marker = destination / '.bundle-sha256'
    if destination.exists():
        if marker.is_file() and marker.read_text().strip() == KOKORO_SHA256 and all((destination / name).is_file() for name in KOKORO_MEMBERS):
            print('Kokoro Sherpa bundle is already installed.')
            return
        raise RuntimeError('kokoro-sherpa exists but is incomplete or unrecognized. Preserve/move that directory before retrying. Legacy data/models/kokoro files are left untouched.')
    archive = model_dir / 'downloads' / KOKORO_ARCHIVE
    download(client, KOKORO_URL + KOKORO_ARCHIVE, archive, KOKORO_SHA256)
    with tempfile.TemporaryDirectory(prefix='.kokoro-setup-', dir=model_dir) as temporary:
        with tarfile.open(archive) as source:
            selected = []
            for member in source:
                if member.name in {'kokoro-multi-lang-v1_0/' + name for name in KOKORO_MEMBERS}:
                    if not member.isfile():
                        raise RuntimeError('Unexpected link/non-file in model bundle')
                    selected.append(member)
            if {Path(m.name).name for m in selected} != KOKORO_MEMBERS:
                raise RuntimeError('Incomplete model bundle')
            source.extractall(temporary, members=selected, filter='data')
        root = Path(temporary) / 'kokoro-multi-lang-v1_0'
        (root / '.bundle-sha256').write_text(KOKORO_SHA256 + '\n')
        root.rename(destination)
    archive.unlink()  # Keep the verified installed model, not a second compressed copy.
    print('Installed CPU Kokoro model, voice table and tokens for sherpa-onnx.')


def install_piper(client, model_dir):
    # This is the voice host used by the maintained OHF Piper downloader,
    # not the archived original GitHub application's binary releases.
    response = client.get(PIPER_URL + 'voices.json')
    response.raise_for_status()
    voice = response.json()['en_US-lessac-medium']
    for remote, metadata in voice['files'].items():
        if remote.endswith(('.onnx', '.onnx.json')):
            checksum = metadata['md5_digest']
            if len(checksum) != 32:
                raise RuntimeError('Missing official Piper checksum')
            download(client, PIPER_URL + remote, model_dir / 'piper' / Path(remote).name,
                     checksum, 'md5', metadata['size_bytes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=['kokoro', 'piper', 'all'])
    parser.add_argument('--model-dir', type=Path, default=Path(os.environ.get('BBS_MODEL_DIR', 'data/models')))
    args = parser.parse_args()
    args.model_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    # Honor the inherited proxy/CA settings. Never bypass TLS or Python metadata.
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name, installer in [('kokoro', install_kokoro), ('piper', install_piper)]:
            if args.provider not in {name, 'all'}:
                continue
            try:
                installer(client, args.model_dir)
            except httpx.HTTPStatusError as error:
                failures.append(name)
                print(f'{name}: HTTP {error.response.status_code} from {error.request.url.host}. Check network/proxy policy and the official model host/CDN access.', file=sys.stderr)
            except httpx.ProxyError as error:
                failures.append(name)
                host = 'huggingface.co' if name == 'piper' else 'github.com and release-assets.githubusercontent.com'
                print(f'{name}: proxy/network policy refused the model download ({error}). Allow the official host {host} and its required CDN redirects; do not disable TLS verification.', file=sys.stderr)
            except (httpx.HTTPError, OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as error:
                failures.append(name)
                print(f'{name} setup failed ({type(error).__name__}): {error}', file=sys.stderr)
    if failures:
        print('Incomplete providers: ' + ', '.join(failures) + '. The app can still use the other installed local engine or device speech. Check Settings for status.', file=sys.stderr)
        return 1
    print('Models stay local. Review the upstream model/voice licenses before redistribution.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
