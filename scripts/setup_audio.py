#!/usr/bin/env python3
"""Explicit, checksum-verified downloads. Never called by application startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import httpx

KOKORO = {
    'kokoro-v1.0.onnx': 'beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a',
    'voices-v1.0.bin': 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d',
}
KOKORO_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=['kokoro','piper','all'])
    parser.add_argument('--model-dir', type=Path, default=Path(os.environ.get('BBS_MODEL_DIR','data/models')))
    args = parser.parse_args()
    # Inherited HTTPS proxy and trust; never disable certificate verification.
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        if args.provider in ['kokoro','all']:
            for name, checksum in KOKORO.items():
                download(client,KOKORO_URL+name,args.model_dir/'kokoro'/name,checksum)
        if args.provider in ['piper','all']:
            response=client.get(PIPER_URL+'voices.json');response.raise_for_status()
            voice=response.json()['en_US-lessac-medium']
            for remote, metadata in voice['files'].items():
                if remote.endswith(('.onnx','.onnx.json')):
                    checksum=metadata['md5_digest']
                    if len(checksum)!=32:raise RuntimeError('Missing official Piper checksum')
                    download(client,PIPER_URL+remote,args.model_dir/'piper'/Path(remote).name,
                             checksum,'md5',metadata['size_bytes'])
    print('Models stay local. Review the upstream model/voice licenses before redistribution.')

if __name__=='__main__':main()
