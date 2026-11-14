# Pi Satellite (`pi3-local`)

Raspberry Pi 3 Model B v1.2 as a meshmind satellite: agent runner + future
monitor/viz node. Inference stays on the Mini; the Pi never runs models.
Status as of 2026-11-14 (session log below).

## Box
- Raspberry Pi 3B v1.2, 1 GB RAM, 128 GB card (117 GB free).
- Raspberry Pi OS Lite 64-bit (Trixie, 2026-10-06 image, sha256-verified).
- Hostname `pi3-local`, user `hugo-hader-raspberry-pi`, SSH key auth
  (`~/.ssh/pi_raspberry_key` on the MacBook; password login off).
- LAN `192.168.178.165` via 2.4 GHz WiFi (NetworkManager cloud-init
  preset); mDNS `pi3-local.local` (avahi installed).
- Tailnet `100.90.15.70`, `tailscaled` systemd-enabled (survives reboot).
  Re-auth only on key expiry (admin console can disable expiry per machine).
- Cooling: 2-wire fan on TRUE pins 4 (5V) + 6 (GND), spins well.
  (Was briefly on 3V3 during bring-up; moved 2026-11-14.)
- Full-disk backup: `/Volumes/AthenaSSD/pi-backups/` (e2image rootfs 6.5 GB
  verified readable, MBR, bootfs copy, OS image + sha256).

## OpenCode (installed, working with limits)
- OpenCode 1.19.5 (latest) via official install script, `~/.opencode/bin`.
- Config version warning: 1.19.x speaks the V1 schema (`provider` +
  `options.baseURL`), NOT the V2 `providers` + `settings` from current
  docs (silently dropped with "cannot be represented in V1").
- Provider `minilab` → Mini `/v1` over tailnet, dummy key `ollama`
  (Mini ignores it). Config: `~/opi-test/opencode.json` (project-local).
- Models declared (all installed on Mini): `qwen2.5:0.5b` (smoke),
  `gemma3:4b` (chat), `qwen2.5-coder:3b` (code), `nemotron-3-nano:4b`
  (agent), `qwen3:8b` (quality). Limits set to server reality (ctx 4096).
- PROVEN 2026-11-14: single-shot Q&A works (`OPI-OK` via 0.5b).
- FAILED 2026-11-14: agentic coding task (write+run `pi_hello.py`):
  3B coder confabulated paths, created nothing; 4B nano returned empty.
  Hypothesis: 4k server context can't hold OpenCode's agent loop
  (matches repo guidance: 4k-or-below box, single-shot shapes).
- Next candidates: `qwen3:8b` retry (non-thinker, quality pick), then
  Hermes (leaner harness) before declaring the loop infeasible here.

## Hermes Agent (installing)
- Target: Hermes Agent ~v0.23.1 stable (official install.sh, `--skip-browser
  --skip-computer-use`, no desktop) in `~/.hermes`.
- Known ahead: managed Python 3.14 via uv (Pi ships 3.13, installer
  provisions its own); ARM64 supported by installer; 64k-context floor vs
  Mini 4k is THE open risk (trial model? fail closed?).
- Tracking: issue #9 (moved from mml-stack#508, wrong repo, closed).

## Hardware bench (wireframe: PI-SATELLITE-WIRING.md)
- Breadboard (kit white 400-point/30-row, no rail splits seen): RETIRED
  2026-11-14, suspected faulty contacts (LED never lit in any config).
  If scorched: bin it, do not reuse.
- LED/button unproven (blocked on the board, not on the Pi).
- Display (Nokia 5110, labels RST CE DC DIN CLK VCC BL GND confirmed):
  NOT wired yet. Plan: direct M-F Pi→display (skip the board), SPI + luma.
- Temp sensor: unidentified, pending markings.

## Runbook fragments
- SSH: `ssh -i ~/.ssh/pi_raspberry_key hugo-hader-raspberry-pi@pi3-local`
- Health: `vcgencmd get_throttled` (0x50000 seen once = past dip, watch PSU),
  `vcgencmd measure_temp` (~44 °C nominal with fan).
- PSU: use an official 2.5 A supply for 24/7 (past undervoltage dip logged).
- Reflash path (proven this session): image + dd + cloud-init seeds
  (`meta-data`, `user-data`, `network-config`, `ds=nocloud` in cmdline).

## Open threads (2026-11-14)
1. Hermes install result + first smoke test (in flight).
2. qwen3:8b agent retry? (if Hermes also fails, declare loop infeasible)
3. Display direct-wire + viz script (needs SPI enable + reboot).
4. Monitor cron (Mini health + Pi temp/load) + global opencode config.
5. Failover gateway design (models interchangeable, limit/outage proof).
