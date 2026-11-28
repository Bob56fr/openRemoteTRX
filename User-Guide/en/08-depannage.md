# 8. Troubleshooting

## 8.1 The first reflex

1. **Diagnostic** (menu 6.1): it tells you what is wrong and what to do.
2. **Log** (menu 6.2): messages start with an “ORT-NNNN” code.
3. Each code has its own explanation page (cause, what to do): https://bob56fr.github.io/openRemoteTRX/erreurs/
   (search field: type the code).

## 8.2 Common problems

| Symptom | Likely cause | What to do |
|---|---|---|
| The diagnostic does not find the transceiver | transceiver off; wrong port (the transceiver's second port, or “Standard” on Yaesu); transceiver speed different from the one in the wizard; driver missing (Windows) | switch on; go through menu 2.5 again with the command port; set the speed (transceiver sheet) |
| No received audio | transceiver sound card taken by the desktop; microphone forbidden to applications (Windows); level too low (transceiver setting, gain in menu 2.9) | part 1.4; part 2, Windows tab; transceiver sheet |
| Transmission starts but nothing is modulated | in this mode the transceiver takes the voice from its microphone, not from USB (Icom: DATA MOD; Yaesu: MOD SOURCE and REAR SELECT) | transceiver sheet, “Voice through USB” |
| Only DATA modes can transmit | the wizard noted that the voice does not go through USB | set up the transceiver, then run the wizard again and answer “yes” |
| ALC at maximum, distorted audio | transceiver USB input level too high (Icom: USB MOD Level; Yaesu: RPORT GAIN) | part 3.4 |
| The transceiver goes into transmission when the PC starts | an RTS or DTR line of the USB port keys the transmitter (Icom: USB SEND / USB Keying; Yaesu: RPTT SELECT, PC KEYING) | **unplug the USB**, set these settings to OFF (transceiver sheet) |
| Slow Raspberry Pi, choppy audio, transceiver USB dropping out | power supply too weak or overheating (`vcgencmd get_throttled` other than `throttled=0x0`) | official power supply, fan (part 2, Raspberry Pi tab) |
| “Microphone unavailable” in the page | page opened over HTTP | open the address with **https://** |
| Page unreachable from the phone | station stopped; address changed; network on the Public profile (Windows) | menu 1.1; part 4.1; part 2, Windows tab |
| Connected but no audio remotely | UDP does not get through (open port on the router) | VPN (part 5) |
| Dropouts every 15 to 30 s | two devices on the same VPN profile | one profile per device |
| Transmission cut by itself | maximum time reached, phone no longer responding, frequency outside the bands, local operator | normal: the reason is shown in the page and the log |
| Nothing responds any more, “station in safety lockout” alert | repeated failures | part 6.2 |
| Transceiver test refused: “ORT-9313 … the station is running” | the test needs the transceiver for itself | stop the station (menu 1.2), run the test again, restart the station |
| A tool stops with “ORT-9312 … unexpected error” | software fault in an unforeseen case (new transceiver, sound card…) | the message gives the detail file (`plantages` folder): attach it to the help request (part 8.3) |

## 8.3 Asking for help

1. Menu **6.3**: creates a troubleshooting report (zip on the Desktop, or in the account folder on a Pi without a desktop) **without any password** (Windows as well as Debian). From the web console, the
   **“Download the report”** button fetches it directly to your PC or phone. The traces of tools that stopped on an error
   (code ORT-9312) are in the `plantages` folder of the station's state folder, and the report includes them.
   To read it yourself: menu **6.6**, which gives the link to the **analyser**; drop the zip there and the analysis
   runs in your browser (the report is sent nowhere).
2. From the web page: “Report a problem” section (text reviewed before sending).
3. Open an issue on https://github.com/Bob56fr/openRemoteTRX/issues with the **English** form
   (“Report a bug”), describe what you were doing, what you expected, what happened, and attach the report.
4. **Getting help remotely** (station-to-station monitoring, menu **6.5**, to be enabled first: part 9): the person
   helping you creates a 10-character code and reads it out to you; type it at choice 4, then compare out loud the **6
   digits** shown on both sides. Different: answer “no”, the link is erased. Then choose what you
   send (“Diagnostic” recommended; frequency and mode only if you want). They then see the state of your station
   and its error codes, **masked** (no password, no address, no serial number), and can **ask** you for assistance
   mode (news every 30 seconds, for a limited time): you are the one who accepts (choice 7). They
   **cannot command anything** on your station. You stop everything whenever you want (choice 9). They can also
   ask you for your **troubleshooting report** (the one in point 1, fully masked); you can also send it
   yourself (choice 10). On their side, they get an alert on their phone if your station stops giving
   news. **Away from your station**, everything can also be done in the web page, “Monitoring” section: button
   “Get help: I have a code”, comparison of the 6 digits, choice of what is sent, answer to requests, end.
5. **Showing your screen to the person helping you** (shared screen, menu **6.7**, nothing to enable, works even
   before the station is configured): in the text console (terminal or SSH, Debian or Raspberry Pi), choice 1. The
   console shows a 10-character code: read it out, then press Enter. The person helping you opens menu 6.7, choice 2
   (on their PC, Windows included) and types the code: they see your console live, encrypted end to end through the
   rf-diy.com relay. They **cannot type anything**: you type what they tell you (by phone for example). **Ctrl+]**
   stops sharing (your console goes on); quitting the console stops everything; 2 hours at most. Also from the command
   line: `trx-console --partage` (you) and `trx-console --voir CODE` (them). Their window must be at least as large as
   yours (their window title tells them).
