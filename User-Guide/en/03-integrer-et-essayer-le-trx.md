# 3. Integrate the TRX and test it

> **Safety.** Throughout this part: **dummy load** on the antenna socket, **reduced power** (10 W for example),
> nobody near the disconnected antenna.

## 3.1 The configuration wizard (menu 2.1)

The transceiver is only queried **read-only**: no transmission during the wizard. Nothing is saved if you give up
halfway. The values specific to your transceiver are in its sheet:

| Question | Answer |
|---|---|
| Transceiver model | type its name (`ic-7300`, `ftdx10`…) and choose from the list (Hamlib number in the sheet: IC-7300MK2 = 3094, FTDX10 = 1042). For some transceivers, the wizard reminds you of the menus to check (part 1) |
| CAT serial port | the **control** port (Debian and Raspberry Pi: offered automatically; Windows: the COM noted in part 1) |
| Speed | **identical** to the CAT speed set in the transceiver |
| PTT method | **CAT** (offered) |
| Does the voice go over USB? | **yes**, if the transceiver modulates over USB in voice (part 1); otherwise transmission will be limited to data modes |
| Sound cards (receive, transmit) | the **transceiver's** for both (its name is in the sheet) |
| HF spectrum through a second port | the transceiver's **second port** if it has one (Icom IC-7300MK2…); otherwise **none** |
| Bands allowed for transmission | the bands of **your licence**, only. Empty list = receive only |
| Network access | “**Local network or VPN, over HTTPS with a certificate generated here**” (recommended) |
| Accounts | a username (letters, digits, `_`, `-`) and a **long password** (Enter = a strong password is generated: write it down); Enter on an empty username to finish |
| Maximum transceiver power | your transceiver's (often **100** watts) |
| Maximum duration of a transmission (TOT) | **90** seconds (default value, ceiling 120) |
| Replay of recordings | **no** (default answer) |

At the end, the wizard shows the address to open (`https://<station-address>:8443`) and the **certificate
fingerprint** (useful for the Android app, part 4).

## 3.2 The diagnostic (menu 6.1)

It reviews everything without changing anything: each line is **OK**, to **watch** or **failed**, with what to do.
Fix each failure before going further (menu 8.1 for a setting, or run the wizard again).

Common failures at this stage: wrong port (the transceiver's second port instead of the control one; Yaesu: Standard
instead of Enhanced), transceiver speed different from the one in the wizard, transceiver sound card taken by the
desktop (part 1.4); on a Raspberry Pi, a power supply that is too weak (“undervoltage”, part 2).

## 3.3 The guided transceiver test (menu 2.2)

The station is stopped during the test.

1. **Choice 1, receive only**: CAT link, received audio, frequency and mode change, filter widths. Check that the
   received audio is clean and at a correct level (otherwise: transceiver setting given by its sheet, then receive
   audio gain in menu 2.9).
2. **Choice 2, receive then transmit**: dummy load, reduced power. Each switch to transmit asks you to type
   `TRANSMIT` (or `EMETTRE`).

Copy the **final summary** shown on screen: it is used for the validation report.

## 3.4 Start the station and set the modulation

1. Menu **1.1**: the station starts (the transceiver is always put back in receive at startup). Run a diagnostic again
   (menu 6.1) a few seconds later.
2. Open the page `https://<station-address>:8443` from a phone or a PC on the network (details and certificate
   warning: part 4), and log in.
3. Allowed band, dummy load, voice mode that your transceiver modulates over USB (USB or LSB; on an Icom, USB-D or
   LSB-D, part 1): press **PTT** (toggle: one press to transmit, one press to go back to receive), speak normally for
   a few seconds, press again.
4. Watch the **ALC** in the page: it must move on voice peaks without staying at maximum. Adjust the transceiver's USB
   input level until you get this result (Icom: **USB MOD Level**; Yaesu: **RPORT GAIN** in the menu of the mode in
   use; the exact name is in the transceiver sheet).

## 3.5 The safety tests

Do **all** of them, on a dummy load, before any transmission on an antenna. Each one must end with the transceiver
back in receive (check on the transceiver's screen, not only in the page).

| # | Test | Expected result |
|---|---|---|
| 1 | During a transmission, the page's **STOP** button | immediate return to receive |
| 2 | Transmit without touching anything | countdown and beep 10 s before the end, return to receive after **90 s** |
| 3 | During a transmission, turn off the phone's Wi-Fi (or close the tab) | return to receive in about **2 s** |
| 4 | During a transmission from the phone, lock the screen | return to receive |
| 5 | Set a frequency outside your allowed bands, press PTT | transmission **refused**, message in the page |
| 6 | Transmit **with the transceiver's microphone** (without the station) | the page shows the local operator and blocks remote PTT during the transmission and for 2 minutes after |
| 7 | During a transmission, the **STOP TX** key of the dashboard (menu 1.3) | return to receive |
| 8 | During a transmission, stop the station (menu 1.2) | return to receive |
| 9 | Restart the PC (or the Pi), transceiver on | the transceiver **never** goes into transmit during startup |

A test that does not give the expected result: **do not use the station to transmit**, stop it (menu 1.2) and ask for
help (part 8) with the report from menu 6.3.

## 3.6 Going further (optional)

- **Transceiver qualification** (menu 8.3, `trx-qualif`): for an expert who wants to check everything Hamlib declares
  for your transceiver. Start with choice 2 (exploration without transmission); the report it produces is valuable
  for validating the transceiver sheet. Choice 6 (“qualification case”) runs everything in sequence for a team member
  who came to qualify the transceiver: reading of the transceiver before and after (what must be restored by hand),
  exploration, qualification, the timed safety tests of § 3.5, and a zip report to hand over to the developers.
- **Transceiver profile** (menu 2.3): saves the configuration under a name (“IC-7300 home”) to load it again later if
  you change transceivers.

## 3.7 Report the validation

If your transceiver is not yet validated (list: https://bob56fr.github.io/openRemoteTRX/postes/), your result counts:
open a “Report a bug” issue (even if everything is fine, title “<your transceiver>: commissioning tests”) with the
summary of the guided test, the result of the 9 safety tests and, if it has a sheet, the points it says to check.
