# Glossary

The words of the guide, arranged by theme. The diagram of the building blocks is in
[part 0](00-avant-de-commencer.md#how-it-is-organised).

## The hardware

| Term | What it is |
|---|---|
| **Transceiver**, **TRX**, **Rig** | your radio transmitter-receiver |
| **Station PC** | the computer next to the transceiver, always on, that runs the station: a PC running Debian or Windows, or a Raspberry Pi |
| **Raspberry Pi** | small single-board computer, low power; the Pi 4 (4 GB) or the Pi 5 running Raspberry Pi OS 64-bit can serve as the station PC |
| **Hardware watchdog** | a chip of the Raspberry Pi that restarts it if the system freezes for more than 15 s; enabled by the installation |
| **Station** | the whole transceiver + PC + openRemoteTRX software; “start the station” = start its services |
| **CAT** | *Computer Aided Transceiver*: control of the transceiver by the computer (frequency, mode, transmission…) |
| **Enhanced COM Port** / **Standard COM Port** | the two serial ports that some Yaesu transceivers (FTDX10…) create on the PC through their USB cable: the first one is for CAT, the second one (RTS/DTR lines) is not used by the station |
| **Transceiver sound card** | the sound card built into the transceiver, seen by the PC through the USB cable (“USB Audio CODEC” on Yaesu, “USB Audio Device” on the IC-7300MK2): received audio to the PC, voice to the transceiver |
| **Dummy load** | 50 Ω resistor that replaces the antenna: the transceiver transmits without radiating. Mandatory for all tests |
| **ALC** | transceiver meter that shows whether the modulation is too strong; used to set the voice level |
| **SWR** | standing wave ratio: matching of the antenna. The station can measure it across a band |
| **VFO A / VFO B** | the transceiver's two working frequencies; the page shows which one is active |
| **Split** | receive on one frequency, transmit on another |

## The station software

| Term | What it is |
|---|---|
| **openRemoteTRX** | the name of the project; the Android app has this name, the station is also called “openRemoteTRX” |
| **Hamlib** | the free library that can talk to about 300 transceiver models; each model has a **number** (IC-7300MK2 = 3094, FTDX10 = 1042) |
| **rigctld** | the Hamlib program that keeps the link with the transceiver; it listens only on the PC itself, never on the network |
| **Gateway** (`trx-gateway`) | the heart of the station: serves the web page, checks the accounts, carries the audio and **decides on transmission** |
| **Supervisor** (`trx-supervisor`) | the independent guardian: watches the gateway, rigctld and the PC; it can **only cut** a transmission, restart a service or put the station in safety lockout; sends the alerts |
| **openRemoteTRX Console** (`trx-console`) | the station's control panel in a terminal: install, configure, start, test, update, troubleshoot (numbered menus “2.1”, “2.2”…) |
| **Configuration wizard** (`trx-setup`) | the questions that create the configuration (menu 2.1); it only reads from the transceiver |
| **Dashboard** (`trx-monitor`) | the live status in a terminal (menu 1.3); a single action: STOP TX |
| **Vital signs dashboard** | read-only page (port 8450, Debian and Raspberry Pi) for a small screen near the transceiver or a phone |
| **Indicator** | the station's status light in the top bar (Debian) or next to the clock (Windows); read-only |
| **Guided test** (`trx-hwtest`) | the step-by-step test of the real transceiver (menu 2.2) |
| **Qualification** (`trx-qualif`) | the complete exploration of what Hamlib declares for a transceiver (menu 8.3), for experts |
| **`station.toml`** | the station's configuration file: transceiver, ports, accounts, allowed bands, safety settings |
| **Transceiver profile** | a transceiver configuration saved under a name, to change transceivers (menu 2.3) |
| **Module** | an optional feature that runs next to the gateway (DX Cluster, group presence…) |
| **Signed update** | the Debian packages are signed: the update over the Internet (menu 7.1) refuses a package whose signature does not match; an unsigned zip (menu 7.3) asks for a confirmation |

## User side

| Term | What it is |
|---|---|
| **Web page** | the station's interface in a browser, at the address `https://<station-address>:8443` |
| **Android app** | the openRemoteTRX app: the same as the page, plus transmitting with the screen off, the headset, the car |
| **Android Auto** | the app's display on the car screen: listening, memories, PTT, no graphics |
| **Driving mode** | the app's reduced screen in the car: no touch PTT |
| **Operator account** | username + password that allow controlling the transceiver and transmitting; **one per device** (`PC`, `S25`…), managed in menu 4.3 |
| **Visitor** | receive-only account: listens and sees the screen, no command |
| **Pairing** | adding the station to the app, with the **QR code** of menu 4.1 |

## Transmission safety

| Term | What it is |
|---|---|
| **PTT** | *Push To Talk*: switching to transmit |
| **Toggle PTT** | one press to transmit, one press to go back to receive (never “as long as you press”) |
| **STOP** | immediate return to receive, always available |
| **TOT** | *Time Out Timer*: maximum duration of a transmission (90 s by default, 120 s at most), with a beep 10 s before the cut |
| **Absolute TOT** | duration beyond which the supervisor cuts any transmission, even one made with the transceiver's microphone (135 s; 5 minutes if the operator touched the transceiver just before or during it) |
| **Heartbeat** | the sign of life the phone sends twice a second during transmission; if it is missing for 2 s, back to receive |
| **Allowed bands** | the frequency ranges where the station accepts to transmit; empty list = receive only |
| **Local operator** | someone using the transceiver in front of it: remote transmission is blocked during their transmission and then for 2 minutes |
| **Transmit audio gate** | the audio path to the transceiver, opened by the gateway only during an authorised transmission |
| **Safety lockout** | the state the supervisor puts the station in after repeated failures: stopped safely (receive, access cut), it waits for an intervention; reactivate it with menu 1.4 (“Reactivate the station”) |
| **Transceiver timer** (TX TIME OUT TIMER) | the transceiver's own cut, independent of the station: the last barrier |

## The network

| Term | What it is |
|---|---|
| **Local network** (LAN) | the home network, behind the internet box |
| **Port 8443** | the port where the gateway receives the page and the app |
| **HTTPS**, **certificate** | the encryption of the link; the station creates its own certificate (“self-signed”): the browser warns the first time |
| **Certificate fingerprint** | the summary of the certificate that the app remembers to refuse a fake station |
| **WebRTC** | the technique that carries the live audio, over **UDP** |
| **VPN** | an encrypted tunnel that puts the phone “inside” the home network, from anywhere (WireGuard, Tailscale…) |
| **VPN profile** | the keys of one device in the VPN: one profile per device, never shared |
| **Open port** | the internet box letting traffic in from the Internet to the station; requires a real certificate and a strong password |
| **SSH** | the encrypted connection that opens a terminal of another machine from your PC: `ssh -l <account> <address>`; used to drive a Raspberry Pi without a screen |
| **CGNAT** | address shared by the provider between several customers: no port can be opened, a VPN is needed |
| **ntfy** | the notification service that carries the station's alerts to your phone |
| **ORT code** | the number of a station message (“ORT-5031”); each code has its explanation page |
