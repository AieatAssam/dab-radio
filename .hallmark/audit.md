# Hallmark audit · DAB listening deck

**Review:** Main QA visual and playback review passed at 320 px and 1440 px. Captures for the other responsive widths remain with QA. The live browser snapshot showed the reported playlist, selected service, and DLS radio text; Playwright reported zero console errors or warnings.

**Critique:** Philosophy 5 · Hierarchy 4 · Execution 4 · Specificity 5 · Restraint 4 · Variety 4.

**Audit findings:** No outstanding visual or accessibility blockers identified. Radio text is the primary listening surface; detailed receiver and stream telemetry stays in a closed disclosure. Broadcast codec and browser delivery codec have separate labels. Missing backend values render as em dashes. Tune, pause, and resume use fresh live stream requests; spectrum data comes from the Web Audio analyser.

**Scope:** Frontend only. Backend integration remains with the main agent.

**Final integration verification:** Chromium playback advanced continuously to 13.4 seconds with live DLS and nonzero analyser pixels. The observed decoded audio-frame error count and server stream/reconnect/overflow counters were zero during that check. Responsive QA found no horizontal overflow at 320, 375, 414, 768, and 1440 px. Ten backend tests pass. The systemd service is active and enabled; its LAN homepage and state endpoint return HTTP 200. RF continuity remains reception-dependent.

**Controls:** A fresh Chromium run verified audible-volume initialization, play, pause with the stream detached, and resume with advancing playback time. With all three EQ bands at +6 dB, adaptive headroom displayed −24 dB and the measured output peak was 0.0293 (below full scale). Reset EQ worked. Playback startup includes buffering; the checks wait for advancing media time rather than assuming a fixed five-second startup.

## Artifacts

- `web/index.html`
- `web/app.js`
- `web/styles.css`
- `tokens.css`
- `web/fonts.css` and `web/fonts/` (vendored by main)
- `.hallmark/preflight.json`
- `.hallmark/log.json`
- `.hallmark/audit.md`
- `.agents/skills/hallmark/`


## Metadata update verification

Native DL+ decoding passed CRC, Unicode, malformed-command and typed-tag tests. All 28 Python tests pass. SPI service information and logos were fetched from real BBC and Bauer RadioDNS providers; no programme guide was fabricated when unpublished. Live Magic Radio DAB+ playback, DLS and nonzero analyser pixels worked with SPI enabled; no browser JavaScript errors. Responsive widths 320, 375, 414, 768 and 1440 had no horizontal overflow, and statistics stayed closed. Station logos use a compact thumbnail to protect listening controls; broadcast slideshow images retain their full presentation.

The adaptive full scan completed all 38 channels in 209 seconds and retained 91 audio services, including 17 on weak Birmingham 11C. Source coverage references and acquisition timing rationale are in README.md.

## Mini-player review

The compact Winamp player preserves the existing token palette, fonts and listening hierarchy. It exposes only track/radio text, audio-driven visuals and basic controls. Critique: P4 H4 E4 S5 R5 V4. Native browser window chrome is used; there is no redrawn title bar or false always-on-top claim.

Live Chromium checks passed for the HTTP LAN popup and genuine native Document PiP on localhost. Six visualisation modes cycle by click; a non-default mode persisted after reopening. Play, Stop, Previous, Next, volume and mute controlled the owner's single audio element. Navigation stayed within the selected ensemble and restored the original station. Closing the mini-window left audio playing; closing the owner closed the popup. Blocked popups produced a clear message. Both the main app and mini-player had no horizontal overflow at their checked widths (main: 320/375/414/768/1440; mini: 320/375/414/768). No browser JavaScript errors were observed. Renderer paths also received a deterministic analyser fixture to cover every mode without retuning RF.

Artifacts: `output/mini-player/playing.png`, `output/mini-player/final.png`, and the verification scripts beside them. The backend and systemd service were unchanged.
