# DAB Radio

This Raspberry Pi hosts a real RTL-SDR DAB/DAB+ network audio player.

## Working agreements

- Use `gpt-6-luna` subagents for bounded implementation work when available, as requested by the owner. Keep delegation concise and file ownership disjoint.
- Read `.agents/skills/hallmark/SKILL.md` for interface changes. Maintain `.hallmark/` project records and `tokens.css`.
- The interface takes its inspiration from Winamp: beautiful, rich, focused on listening. Broadcast radio text is essential and prominent. Technical statistics belong in a panel closed by default.
- Spectrum visualisations must use actual audio data. Never animate fictional signal or reception metrics.
- Clearly distinguish the broadcast encoding/bitrate/channel mode from the browser delivery encoding.
- Preserve playback headroom and show real buffering and receiver error counters. Do not promise zero reception errors or recover audio missing from a broadcast.
- A single physical tuner receives one multiplex at a time. Scanning interrupts reception; make that visible.
- Runtime state lives in `data/`. Do not commit recordings, receiver logs, virtual environments, or browser profiles.
- The service listens on port 8090. Port 8080 belongs to another application.

## Validation

Run the Python tests and real browser checks after material playback or receiver changes. Check the UI at 320, 375, 414, 768 pixels and desktop width. Verify real MP3 playback and radio text with the connected dongle where available.
