# DAB Radio

FastAPI backend and browser client for one DAB receiver, hosted on a Raspberry Pi 4 Model B Rev 1.2. The backend owns the receiver process; systemd supervises the backend and its child processes as one service.

Open **http://10.109.208.199:8090/** from a browser on the same network. The initial scan found 90 audio services across four multiplexes; the station catalogue and selected station persist in `data/`.

## Runtime layout

| Component | Listener | Managed by |
| --- | --- | --- |
| FastAPI (`app:app`) | `0.0.0.0:8090` | `dab-radio.service` / Uvicorn |
| `welle-cli` web mode | port `7979` | Backend process (`DAB_MANAGE_RECEIVER=true`) |

The `welle-cli` command-line help on this host confirms `-w <port>` enables its built-in web server. Upstream examples use port 7979. The backend launches one receiver process; do not run a second standalone receiver service alongside it. The upstream `welle-cli` socket implementation binds its web listener to all IPv4 interfaces, so port 7979 may be reachable from other hosts as well. Check the deployed binary's listener and restrict network access if clients should reach it only through the API. See the [welle-cli options](https://github.com/AlbrechtL/welle.io/blob/master/src/welle-cli/welle-cli.cpp) and [socket binding code](https://github.com/AlbrechtL/welle.io/blob/master/src/various/Socket.cpp).

Port 8080 is already occupied by another service on this host and is not used or managed here. The API is configured for port 8090.

## Install and run

The Python dependencies are pinned in `requirements.txt`. On a fresh checkout, create the environment with `python3 -m venv .venv` and install them with `.venv/bin/pip install -r requirements.txt`. This host already has the RTL-SDR libraries. Build the patched DAB/DAB+ decoder with `./scripts/build-decoder.sh` before installing the service (build dependencies are listed below). The deployment scripts do not install or upgrade Python packages.

Run these commands as the `aieat` account from the checkout:

```bash
./scripts/install.sh
./scripts/start.sh
```

`install.sh` checks that `app.py`, `.venv/bin/uvicorn`, and `build/welle/welle-cli` exist, installs `systemd/dab-radio.service` into `/etc/systemd/system`, reloads systemd, and enables the unit for boot. It does not start the receiver. `start.sh` returns the current status when the unit is already active; otherwise, it checks that ports 8090 and 7979 are free before starting the unit. The unit runs one Uvicorn worker with access logging disabled to avoid per-request journal writes.

Useful service commands:

```bash
sudo systemctl status dab-radio.service
sudo journalctl -u dab-radio.service -f
sudo systemctl stop dab-radio.service
```

The service runs as `aieat` and uses the existing checkout and virtual environment. Ensure the account has permission to access the SDR device through the host's udev rules and device groups.

## Listening interface

The player is a Winamp-inspired listening deck with live radio text prominent beside the station and transport controls. It labels broadcast format separately from MP3 delivery. The spectrum belongs to the decoded audio view; signal and stream diagnostics sit in a details drawer that is closed by default.

## Receiver and RF limits

This deployment has one tuner and can receive one DAB ensemble at a time. A recent live check of BBC Radio 2 on 12B reported 21 dB SNR and one FIC CRC error. These are observations from one reception period. Reception varies with antenna, location, interference, and device conditions. RF reception is real time; software cannot guarantee zero dropped RF frames.

The live MP3 probe showed startup/re-encoding peaks around +3 dB. Browser playback applies at least 6 dB of headroom before the EQ and a compressor/limiter before output. EQ boosts increase the attenuation automatically. These protections cannot repair distortion or audio frames already lost in the broadcast or RF reception.

The service uses `Nice=-5` and `CPUWeight=200` to give receiver processing preference under CPU contention. Listening from another device avoids running the visualisation workload on the receiver Pi.

The Pi 4 is the deployment target, so the service runs a single Uvicorn worker without reload mode. Keep receiver decoding on demand where supported, and avoid running duplicate receiver or browser automation workloads during live RF checks.

## Tests and browser checks

Run backend tests from the project virtual environment:

```bash
.venv/bin/python -m pytest -q
```

The current suite checks tune validation, nullable receiver state, broadcast-versus-delivery codec fields, MP3 route headers and chunk forwarding, shared stream fan-out, slow-subscriber overflow disconnection, and unsubscribe cleanup. These tests mock the audio upstream and do not start the FastAPI lifespan, Uvicorn, or SDR hardware. RF continuity is not asserted because real-time reception can lose frames.

The official Playwright CLI skill is installed under `.agents/skills/playwright`. Chromium is available at `/usr/bin/chromium`; Node.js/npm provide the CLI's `npx` wrapper. The review config at `output/playwright/dab-review/chromium.config.json` selects the system Chromium binary, so browser checks do not need a second browser download. Keep browser artifacts under `output/playwright/`.

## Rich metadata and scanning

DL+ is decoded natively from the selected programme's existing PAD data. Typed title, artist, album, presenter and programme fields are exposed only when transmitted; plain radio text is not guessed into artist/title fields. The audio decoder and MP3 encoder are unchanged.

SPI service information, station logos and published programme schedules are acquired through RadioDNS over the internet. These are labelled separately from broadcast MOT slides, which take priority. The existing receiver does not decode the dedicated packet-mode binary SPI broadcast carousel. Using the broadcaster's hybrid SPI service adds no extra RF subchannel decoding and never retunes the receiver. The bounded background worker uses a separate HTTP client, 2 MiB XML limit, public endpoints, a 40-second operation cap and cached results. Missing internet or unpublished guide information does not stop listening.

The custom decoder build is reproducible: install `build-essential cmake pkg-config libasound2-dev libfaad-dev libmpg123-dev libfftw3-dev librtlsdr-dev libmp3lame-dev xxd`, then run `./scripts/build-decoder.sh`. Its revision, patch attribution and native tests are documented in `patches/README.md`. Install Python dependencies again with `.venv/bin/pip install -r requirements.txt` before restarting after an update.

Full Band III scanning is adaptive: approximately 3 seconds on empty channels; at least 8 seconds and 3 seconds of stable, complete labels on good signals; up to 15 seconds for incomplete signalling, or 30 seconds for weak acquired ensembles. SNR alone does not count as an acquired ensemble. These are conservative receiver-style acquisition limits, not a claim that all commercial radios use one timeout. Unsuccessful scans retain previously discovered stations and flag their channels stale. Cancel restores the previous station; an already-playing browser resumes after the scan finishes or is cancelled.

For the B63 area, useful local channels include Birmingham on **11C** and Dudley–Stourbridge on **8A**; indoor reception is not guaranteed. The national channels remain 11A, 11D and 12B. Sources: [Ofcom Birmingham planning](https://www.ofcom.org.uk/tv-radio-and-on-demand/coverage-and-transmitters/dab-coverage-planning), [DigiMux Dudley–Stourbridge operator](https://www.digimux.co.uk/), [WorldDAB FIC acquisition guidance](https://www.worlddab.org/public_document/file/1508/FIC_Guidance.pdf?1659358928=).

## Mini-player

Use the small window icon beside Refresh to open the mini-player. It shares the main tab's audio session, limiter, EQ and volume. Previous/Next follow the main playlist's current search, ensemble and favourites filters. Stop releases the live stream; Play starts fresh live audio. Closing the mini-player keeps listening in the main tab; closing the main tab closes the mini-player.

Click the visualisation (or focus it and press Enter/Space) to cycle through LED Spectrum, Mirror Spectrum, Oscilloscope, Radial Corona, Flowing Ribbon and Spectrogram. The chosen mode is remembered locally. Each mode uses the existing Web Audio analyser; no second audio stream or SDR decoder is started. Rendering uses the mini-window's animation clock so it can keep drawing while the opener is in the background. Reduced-motion preferences lower the frame rate; the spectrogram uses a small offscreen image buffer.

On a supporting desktop browser with HTTPS or a localhost address, the app opens a native Document Picture-in-Picture window that stays on top. At the ordinary `http://10.109.208.199:8090/` LAN address it opens a standard popup, which websites cannot force above other apps. The mini-player labels this difference; desktop window controls may offer a separate always-on-top setting. See [MDN's Document PiP support and secure-context requirements](https://developer.mozilla.org/en-US/docs/Web/API/Document_Picture-in-Picture_API).

To use native pinned mode from another computer without changing the Pi's service or configuring TLS, an optional SSH tunnel makes the app available on localhost:

```bash
# Run on the computer with your browser; leave this terminal open.
ssh -N -L 18090:127.0.0.1:8090 aieat@10.109.208.199
```

Then visit `http://localhost:18090/` in a browser that supports Document PiP and open the mini-player. Browser popup permissions still apply to fallback windows.
