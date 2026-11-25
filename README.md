# openRemoteTRX

*[Version française](README.fr.md)*

Remote control of an amateur radio transceiver from the browser of a smartphone, tablet or PC, or from the Android app: **receive and transmit**, with transmit safeguards running on the station itself.

*Page last updated: 25 November 2026 (repository code: station 0.288.0, Android app 0.93.0).*

> **Status: under active development.** Validated with an **Icom IC-7300MK2** on a Windows PC and on Debian 13. **Yaesu FTDX10** qualified on a dummy load (validation in progress). Other radios should work (see below); the status of every radio tried is published on the [radios page](https://bob56fr.github.io/openRemoteTRX/postes/). Use it on a **dummy load** at reduced power first.

## What it does

- **Web control page** served by the station over HTTPS: frequency (drag the digits, keypad, bands, steps), modes, filters (FIL presets and widths), NR / NB / Notch / ATT / preamp / AGC / compressor / power, squelch read from the radio, S-meter, Po / SWR / ALC meters, shared memories.
- **Android app** (Android 10 and later): same features, **Android Auto** (player, memories from the steering wheel, explicit transmit state), driving mode, Bluetooth headset button. A **Lite** version for Android 8 and 9 is being tested in a [separate repository](https://github.com/Bob56fr/openRemoteTRX-lite).
- **Two-way audio** over WebRTC (Opus), with the phone's or PC's microphone; voice equaliser and effects, final limiter on the station.
- **Toggle PTT only** (never press-and-hold), with a "transmit allowed" box to tick first, and an always-visible **STOP**.
- **Waterfall of the received audio**, the **radio's HF spectrum** (Icom, through the second CI-V port) with finger tuning, and **DX Cluster spots** (amateur clusters, Reverse Beacon Network, CB page) on the spectrum.
- **SDR receiver** alongside the radio (SDRplay RSP, RTL-SDR): waterfall, zoom, separate listening, left / right ear.
- **FreeDV RADE** reception (digital voice decoded by the station) and a list of active FreeDV stations.
- **SWR sweep** across a band, with a chart and a shareable image.
- **Listener accounts** (receive only) and **live streaming** to a listening server (off by default).
- **Remote power on / off** of the radio (off by default).
- **Group presence "Friends"** (off by default): who is in a QSO, listening, at the shack; QSY to a friend after confirmation. The relay only carries encrypted states it cannot read; the feature has no right over the radio.
- **Station-to-station monitoring**: a friendly station can help troubleshoot (error codes, redacted report), at the operator's request.
- **openRemoteTRX Console** on the station, in a terminal or **in the browser** (port 8444, administrator accounts): setup wizard, diagnostics, dashboard, guided radio test, updates, configuration editor, troubleshooting report, automated tests. Read-only vital-signs dashboard (port 8450).
- **Page, app and console in four languages**: English, French, German, Spanish.
- Public **error code catalogue** ([ORT codes](https://bob56fr.github.io/openRemoteTRX/erreurs/)) and phone alerts through ntfy.
- **openRemoteTRX-Autotest**: pre-qualify a radio from Chrome, nothing to install ([page](https://bob56fr.github.io/openRemoteTRX/autotest/)).

## Transmit safeguards

The station, not the app, decides when to transmit. The safeguards run on the station, even if the phone freezes or loses its network:

- maximum transmit time (90 s by default, 120 s ceiling), with a warning;
- client heartbeat while transmitting: without it for 2 s, back to receive;
- immediate return to receive if the connection drops; always in receive at start-up;
- only one operator transmits at a time; the remote microphone reaches the radio only during that operator's own confirmed transmission;
- the radio's real state is read back continuously; the band is checked on the actual transmit frequency (split, XIT, second receiver); frequency and mode changes are refused while transmitting;
- an **independent supervisor** reads the radio itself and cuts the transmission if the gateway freezes, or beyond an absolute time limit; as a last resort, a **safety lockout** (receive only, waiting for an intervention);
- the person **at the radio** keeps priority: if they transmit on the radio's microphone or change frequency or mode, remote transmission is blocked for a few minutes;
- when in doubt, the station does not transmit.

Details in `CLAUDE.md` ("Règles de sécurité d'émission") and `docs/` (in French).

## Requirements

- A **radio supported by [Hamlib](https://github.com/Hamlib/Hamlib)** (about 300 models), with CAT and audio over USB (built-in USB interface, or an external interface such as Digirig or SignaLink).
- A **station**: a PC running **Debian 12 or 13** (guided installation), or a **Windows 10/11 PC**. Hamlib 4.5 or newer, Python 3.11 or newer.
- **Raspberry Pi 4**: installation prepared (headless, everything over SSH), first feedback from a beta tester; not yet validated. Pi 3 not recommended.

## Installation

**First station?** Follow the step-by-step **operator guide**, with a checklist at the end, in English, French, German and Spanish: [User-Guide/](User-Guide/README.md) (web page: https://bob56fr.github.io/openRemoteTRX/guide/en/). In a hurry? [Quick start](User-Guide/en/demarrage-rapide.md), about 15 minutes. What follows is a summary.

Signed packages are published under [Releases](https://github.com/Bob56fr/openRemoteTRX/releases).

### Debian (recommended)

1. Get the `trx-remote-debian-X.Y.Z.zip` package and unzip it.
2. In that folder: `sudo bash install.sh` (dependencies, service account, systemd services).
3. Open **openRemoteTRX Console** (applications menu or `trx-console`) and run the **setup wizard** (menu 2.1): radio, ports, sound cards, network access, accounts.
4. Run the **guided test** (menu 2.2) on a dummy load.
5. On the phone, open `https://<station-address>:8443`.

Later versions are installed from openRemoteTRX Console (menu 7.1 over the Internet, signature checked; menu 7.3 from a zip file).

### Windows

1. Install **Hamlib 64-bit** (`hamlib-w64-X.Y.Z.exe`, [Hamlib releases](https://github.com/Hamlib/Hamlib/releases)).
2. Get the `trx-remote-windows-X.Y.Z.zip` package, unblock it (Properties), extract it, double-click **`installer.cmd`**. Python is installed if missing (with your consent).
3. Start menu > **openRemoteTRX**: a single shortcut opening openRemoteTRX Console (configuration, diagnostics, start and stop the station, dashboard, radio test, logs). Uninstall: Settings > Apps.

The station starts at logon, without a window. Full guide (French): `windows/notice-windows.html` (shipped in the package). A **Microsoft Store** version is in preparation.

## Access from outside

The project imposes **no VPN**: use your own (WireGuard, Tailscale…) or expose the port with TLS. Passwords are stored as hashes, repeated attempts are slowed down, and unencrypted network access is refused; the station can install its own certificate authority on your devices. A network quality probe explains dropouts (phone, mobile network, local network). **Known limit**: WebRTC audio uses UDP; behind some routers or mobile networks (strict NAT) it may not get through without a VPN or a TURN relay. See `docs/acces-distant.md`.

## Still to do or to validate

- **Android app**: invitation-only testing (Google Play); real in-car tests (Android Auto) still in progress. The web page itself stops transmitting as soon as it is hidden.
- Real remote access over 4G/5G, Raspberry Pi validation, full validation of the FTDX10 (remote split) and the FTDX101.
- Review of the German and Spanish translations by native speakers.
- The detailed documentation (`docs/`) is in French.

## Regulations

You remain responsible for complying with your licence and your country's regulations, **including for remote operation**. Some band buttons (85, 45, 11 m) are for **listening**: they are not amateur bands.

## Reporting problems, contributing

- From the page: **"Report a problem"** section (the report is shown before sending), then openRemoteTRX Console, menu 6.3 (troubleshooting report, no passwords or serial numbers).
- On GitHub: *Issues* tab, with the form in your language (English, French, German, Spanish).
- Contributing: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`). Copyright (C) 2026 RF-DIY.COM.

If you modify this software and make it available to others over a network, you must offer them the source code of your version.
