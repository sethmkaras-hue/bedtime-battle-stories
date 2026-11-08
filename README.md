# Bedtime Battle Stories

Private, mobile-first bedtime tournament app for Ubuntu. Phase 1 is a working skeleton with placeholder story playback; no AI services or paid API calls.

## Run on Ubuntu

```bash
sudo apt install python3 python3-venv
bash START_APP.sh
```

Open `http://SERVER_LAN_IP:8502` from a device on the same network. Port 8502 avoids the existing Streamlit app on 8501.

## Test

```bash
.venv/bin/python -m pytest -q
```

## Status

The creature database is empty by design until Phase 2. The pronunciation buttons use browser speech synthesis, which is not a verified scientific pronunciation engine. The five-minute inactivity timeout stops browser speech on the story player; full narrated audio is planned for later phases. Tournament simulation, advancement, AI story writing, illustrations and narrated playback are not yet implemented.

Never expose the app to the public internet or commit API keys.
