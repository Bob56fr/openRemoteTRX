# Quick start

For the impatient: your transceiver in the browser in a quarter of an hour. The rest of the guide explains each step
in detail; come back to it at the first problem.

## You need

- a transceiver known to Hamlib, connected to the PC: a USB cable for most recent transceivers (control and audio),
  otherwise an interface such as Digirig or SignaLink;
- a PC running **Debian 12 or 13** or **Windows 10 / 11** 64-bit, or a **Raspberry Pi 4 or 5** (Raspberry Pi OS
  64-bit, official power supply), always on near the transceiver, connected to the internet box;
- a **dummy load** for the first transmission;
- a phone or a PC with a recent browser.

## 0. First, the transceiver TOT (2 min)

> **Safety.** The **TOT** (*Time Out Timer*) is the timer that cuts the transmission after a maximum time.
> Set the transceiver's one **before anything else**.

**Why?** Remotely, you cannot see your transceiver. If the station PC freezes, if the USB cable comes loose or if a
program crashes during a transmission, nobody can put the transceiver back to receive any more: it would keep
transmitting a carrier, block the frequency, heat up, and you would remain responsible.

**What it is for.** The station has its own TOT (90 s by default) and a supervisor that watches it. The transceiver
TOT is the **last barrier**: it is inside the transceiver itself, it cuts even when the PC, the cable or the station
has failed.

**How.** In the transceiver menu, look for “Time-Out Timer” (“Time-Out Timer (CI-V)” on Icom) or “TX TIME OUT TIMER”
and choose **3 minutes**: longer than the station TOT, it never cuts a normal transmission.

The menu path for your brand is in the table below. On the IC-7300MK2, the station reads this setting back at
each connection and warns you if it is OFF.

## Depending on your brand

What changes from one transceiver to another, in one line; the details are in the transceiver sheet when there is
one.

| | Icom | Yaesu | Kenwood | Xiegu |
|---|---|---|---|---|
| USB driver (Windows) | “Icom USB Driver”, version **1.80 or later** | Silicon Labs **CP210x**; “Enhanced” port for control | manufacturer's driver | manufacturer's driver |
| Transceiver TOT | MENU > SET > Function > Time-Out Timer (CI-V) | OPERATION SETTING > GENERAL > TX TIME OUT TIMER | transceiver manual | transceiver manual |
| Voice over USB | MENU > SET > Connectors > DATA MOD = **USB** (transmit in USB-D / LSB-D) | MOD SOURCE = **REAR** and REAR SELECT = **USB**, in each mode | transceiver manual | transceiver manual |
| Status | **validated** (IC-7300MK2) | **in progress** (FTDX10) | not tested yet | not tested yet |
| Sheet | [IC-7300MK2](postes/ic7300mk2.md) | [FTDX10](postes/ftdx10.md) | — | — |

On Linux (Debian, Raspberry Pi), no driver to install. For a transceiver not tested yet: install the USB driver from
its manufacturer's website, and do the three tests of step 5 with particular care.

## 1. Install (5 min)

Download the package of the latest version: https://github.com/Bob56fr/openRemoteTRX/releases

<!-- onglets -->
#### Debian

Extract `trx-remote-debian-X.Y.Z.zip`, open a terminal in the folder obtained, then

```
sudo bash install.sh
```

Log out and log back in at the end.

#### Raspberry Pi

Card prepared with Raspberry Pi Imager (Raspberry Pi OS 64-bit, SSH enabled) and system up to date: part 2,
Raspberry Pi tab. Then the **same package as Debian**: with a desktop, exactly as on Debian; without a desktop, from
your PC:

```
scp -o User=<account> trx-remote-debian-X.Y.Z.zip <pi-address>:
ssh -t -l <account> <pi-address>
```

and on the Pi: `unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh`.
Log back in at the end.

#### Windows

1. First install **Hamlib 64-bit** 4.7 or later (`hamlib-w64-X.Y.Z.exe`):
   https://github.com/Hamlib/Hamlib/releases
2. Right-click `trx-remote-windows-X.Y.Z.zip` > Properties > **Unblock**, then Extract All and double-click
   **`installer.cmd`**.
3. Home network set to the **Private** profile, **sleep disabled**.
<!-- /onglets -->

## 2. Configure (5 min)

Open **openRemoteTRX Console** (Debian: applications menu or `trx-console`; Raspberry Pi without a desktop:
`ssh -t -l <account> <pi-address> trx-console`; Windows: Start menu > **openRemoteTRX**),
then **menu 2.1** (the wizard). The transceiver is only read: no transmission. What matters:

| Question | Answer |
|---|---|
| Model | type the transceiver name (e.g. `ic-7300`, `ftdx10`), choose from the list |
| Port and speed | the transceiver port; the speed set in the transceiver's CAT menu |
| PTT | **CAT** if the wizard offers it |
| Sound cards | the transceiver's one, for receive and for transmit |
| Allowed bands | the bands of **your licence**, nothing else. Empty list = receive only |
| Maximum duration of a transmission (station TOT) | **90** seconds (offered, 120 at most) |
| Network access | “Local network or VPN, over HTTPS” (offered) |
| Account | a username; Enter on the password generates a strong one: **write it down** |

For everything else, Enter keeps the offered value.

## 3. Start and check (2 min)

1. **Menu 1.1**: the station starts, transceiver in receive.
2. **Menu 6.1** (diagnostic): fix each line in **failure** before going further; the line says what to do.

## 4. Connect (1 min)

1. On the phone or a PC at home: `https://<station-address>:8443` (address shown at the top of openRemoteTRX
   Console).
2. Certificate warning: “Advanced” then “Proceed”. This is normal (certificate made by your station); to stop
   seeing it: menu 4.4.
3. Log in with the wizard's account. No sound: tap the sound button, the browser had blocked it.

Reserve the PC's address in your internet box (DHCP reservation): if it changes, the certificate is no longer valid.

## 5. Before the first transmission: three tests (3 min)

> **Safety.** Dummy load connected, reduced power, a band of your licence. The **PTT is a toggle**: one press to
> transmit, one press to go back to receive. After each test, look at the **transceiver's display**, not only the
> page.

| Test | Expected |
|---|---|
| During a transmission, **STOP** button | immediate receive |
| During a transmission, close the tab (or turn off the phone's Wi-Fi) | receive in about 2 s |
| Frequency outside your bands, then PTT | transmission **refused**, message in the page |

A single failed test: **do not transmit**, stop the station (menu 1.2) and read part 8. The nine complete tests are
in part 3.5: do them before transmitting on an antenna.

## Next

- **Android app**: menu 4.1, QR code to scan (app in invitation-only testing, part 0).
- **From outside** (4G, another network): VPN or open port, part 5.
- **Alerts on the phone**: menu 3.5, with a test alert.
- **A problem**: menu 6.1, then the report from menu 6.3 to attach to a request for help (part 8).
- **All the console menus**: https://bob56fr.github.io/openRemoteTRX/console/en/
