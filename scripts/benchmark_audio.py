#!/usr/bin/env python3
"""Generate a small CPU sample and report measured speed; no paid providers."""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.audio.service import AudioService


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('provider',choices=['kokoro','piper'])
    p.add_argument('--voice')
    args=p.parse_args()
    service=AudioService(os.environ.get('BBS_AUDIO_CACHE','data/audio_cache'),os.environ.get('BBS_MODEL_DIR','data/models'))
    try:
        req={'kind':'narration','provider':args.provider,'voice':args.voice or ('af_heart' if args.provider=='kokoro' else 'en_US-lessac-medium'),
             'text':'The stars are shining. A little adventure begins beneath the moon. Everyone is safe, and the world is settling down to sleep.','speed':1,'overrides':{}}
        job=service.submit(req)
        if job.get('fallback'):raise SystemExit('Local provider is unavailable. Install its packages and models first.')
        while job['state'] in ['queued','generating']:
            time.sleep(.2);job=service.status(job['key'])
        if job['state']!='ready':raise SystemExit(job.get('error','Benchmark failed'))
        print(json.dumps({'platform':platform.platform(),'python':platform.python_version(),'threads':os.environ.get('BBS_TTS_THREADS','2'),
                          'peak_process_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),**job},indent=2))
    finally:service.close()

if __name__=='__main__':main()
