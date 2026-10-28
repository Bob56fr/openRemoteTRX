# TRX Remote (openRemoteTRX)

*[Version française](README.fr.md)*

Remote control of an amateur radio transceiver from the browser of a smartphone, tablet or PC: **receive and transmit**, with transmit safeguards running on the station itself.

> **Status: under active development.** Validated with an **Icom IC-7300MK2** on a Windows PC and on Debian 13. Other radios should work (see below) but have not been tried. Use it on a **dummy load** at reduced power first.

## What it does

- **Web control page** served by the station over HTTPS: frequency (drag the digits, keypad, bands, steps), modes, filters, NR / NB / Notch / ATT / preamp / AGC / compressor / power, squelch, S-meter, Po / SWR / ALC meters, shared memories.
- **Two-way audio** over WebRTC (Opus), with the phone's or PC's microphone.
- **Toggle PTT only** (never press-and-hold), with a "transmit allowed" box to tick first.
- **Waterfall of the received audio** in the page, and the **radio's HF spectrum** (Icom, through the second CI-V port) full screen or docked on large screens, with finger tuning.
- **DX Cluster spots** (amateur clusters, Reverse Beacon Network, CB page) shown on the HF spectrum, with the status of each feed.
- **TRX Console** on the station: setup wizard, diagnostics, dashboard, guided radio test, updates, configuration editor, radio temperature thresholds, troubleshooting report, automated tests.
- Colour themes, layouts, link sounds, end-of-transmission beeps (off by default), "Report a problem".

## Transmit safeguards

The station, not the app, decides when to transmit. The safeguards run on the station, even if the phone freezes or loses its network:

- maximum transmit time (90 s by default, 120 s ceiling), with a warning;
- client heartbeat while transmitting: without it for 2 s, back to receive;
- immediate return to receive if the connection drops; always in receive at start-up;
- only one operator transmits at a time; the remote microphone reaches the radio only during that operator's own confirmed transmission;
- the radio's real state is read back continuously; frequency and mode changes are refused while transmitting;
- an **independent supervisor** reads the radio itself and cuts the transmission if the gateway freezes, or beyond an absolute time limit; as a last resort, **safe mode** (receive only);
- the person **at the radio** keeps priority: if they use the radio's microphone or controls, remote transmission is blocked for a few minutes;
- when in doubt, the station does not transmit.

Details in `CLAUDE.md` ("Règles de sécurité d'émission") and `docs/` (in French).

## Requirements

- A **radio supported by [Hamlib](https://github.com/Hamlib/Hamlib)** (about 300 models), with CAT and audio over USB (built-in USB interface, or an external interface such as Digirig or SignaLink).
- A **station**: a PC running **Debian 12 or 13** with a desktop (guided installation), or a **Windows 10/11 PC**. Hamlib 4.5 or newer, Python 3.11 or newer.
- **Raspberry Pi**: planned from the start, but **never tried**. If you want to try it on your own, feedback is welcome.

## Installation

### Debian (recommended)

1. Get the `trx-remote-debian-X.Y.Z.zip` package and unzip it.
2. In that folder: `sudo bash install.sh` (dependencies, service account, systemd services).
3. Open **TRX Console** (applications menu or `trx-console`) and run the **setup wizard** (menu 2): radio, ports, sound cards, network access, accounts.
4. Run the **guided test** (menu 4) on a dummy load.
5. On the phone, open `https://<station-address>:8443`.

Later versions are installed from TRX Console (menu 10 over the Internet, menu 13 from a zip file).

### Windows

Manual installation for now: Hamlib for Windows, Python 3.11 or newer, then in the project folder `pip install -e ".[station]"`, `trx-setup` to configure and `trx-supervisor` to run the station. See `docs/essai-poste-reel.md` (French).

## Access from outside

The project imposes **no VPN**: use your own (WireGuard, Tailscale…) or expose the port with TLS. Passwords are stored as hashes, repeated attempts are slowed down, and unencrypted network access is refused. **Known limit**: WebRTC audio uses UDP; behind some routers or mobile networks (strict NAT) it may not get through without a VPN or a TURN relay. See `docs/acces-distant.md`.

## Still to do or to validate

- **Android app** (foreground service, Android Auto, Bluetooth and steering-wheel buttons): the web page stops transmitting as soon as it is hidden.
- Real remote access over 4G/5G, Raspberry Pi tests, signing of published updates.
- The detailed documentation (`docs/`) is in French.

## Regulations

You remain responsible for complying with your licence and your country's regulations, **including for remote operation**. Some band buttons (85, 45, 11 m) are for **listening**: they are not amateur bands.

## Reporting problems, contributing

- From the page: **"Signaler un problème"** section (the report is shown before sending), then TRX Console, menu 8 (troubleshooting report, no passwords).
- On GitHub: *Issues* tab.

## Licence

[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`). Copyright (C) 2026 RF-DIY.COM.

If you modify this software and make it available to others over a network, you must offer them the source code of your version.
