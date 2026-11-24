# 9. Optional features

All of them are **disabled** at the start. Enable them once the station is validated (parts 3 to 5): menu **5.5**
“Features in service” switches them on or off by number (it also starts the feature's module);
a feature that needs other settings is refused, with the menu where to make them.

| Feature | What it is for | Where to enable it |
|---|---|---|
| Receive-only **Visitors** | accounts that listen to the station and see the screen, with **no** command at all (radio club, demonstration) | menu 4.2, then the “Visitor listening” switch in the page |
| **DX Cluster** | spots on the spectrum and badges on the band buttons | menu 5.1 |
| **FreeDV** RADE V1 (reception) | FreeDV digital voice decoded by the station | decoders to compile (`sudo bash compiler-freedv.sh` in the Debian package folder), then menu 5.5 (“FreeDV reception”); the locator for FreeDV activity: `[freedv] locator` (menu 8.1) |
| **SELCALL** | group-call squelch in SSB | menu 5.5, then the SELCALL section of the page |
| **SWR measurement** | SWR curve of the antenna over a band, in FM, at reduced power | web page or application; the station transmits: allowed bands only |
| **Group presence** | see which friends equipped with openRemoteTRX are in a QSO, and join them | menu 5.3 |
| **Station-to-station monitoring** | get help remotely from someone you trust, or help another operator: station state and error codes, masked and encrypted, without VPN or open port; no command possible towards the station being helped | menu 5.5 (“Monitoring between stations”), then menu 6.5 or the “Monitoring” section of the page (part 8.3) |
| **Breizh Audio Box** | voice processing on another PC of the local network | menu 5.2 |
| **Live broadcast** | let a few **listeners** on the Internet hear the transceiver's audio, without an account on the station: they listen on the page of a broadcast server (private channel with username and password, or public); **DIFFUSION** indicator always visible in the page; your voice during your transmissions is broadcast only if you ask for it; outside your bands, silence for the listeners (unless set otherwise): their page gives the reason (outside the bands, transmission without your voice, no more audio from the transceiver), as do menu 5.6 and the 🔇 indicator; alert on the phone at the start and at the end | menu 5.6 (server and secrets given by the server administrator), menu 5.5 (“Live broadcast”), then menu 5.6 or the “Live broadcast” section of the page to start and stop |
| **Replay** of a recording | transmit again a recording of the reception | granted in the wizard; generally **forbidden** in the amateur service |
| **SDR receiver** (SDRplay) | second waterfall and listening (AM, FM, SSB, CW) of a receive-only SDR, next to the TRX; SDR audio muted during any transmission; TRX / SDR balance and, on headphones, one source per ear; waterfall zoom (“Zoom − / +” around the listened frequency, ◄ ► to move the window), colour palette, width (at most the one chosen in menu 2.4) and antenna A / B from the page; DX Cluster spots on the SDR waterfall (tap a spot: the SDR listens to it, the TRX does not move); the station slows down or suspends the SDR by itself if it is too loaded; SDR IN STANDBY when nobody has shown its section or listened to it for 1 minute (less load and heat), woken in a few seconds when the section is opened (“SDR: leaving standby, a few more seconds…”); SDR chosen and set in menu 2.4 of openRemoteTRX Console (search on all USB ports and hubs); “TRX QSY” to a frequency read on the SDR; SDR running: below the TRX frequency, a purple “SDR” line (frequency, mode, filter being listened to; tapping it opens the SDR section on its waterfall), on the right two bargraphs of the audio heard (TRX: tap = mute in the page, reset at each connection; SDR: tap = listening started or stopped, like “Listen”), “S-TRX” and “S-SDR” S-meters (S-SDR while listening to the SDR, approximate “≈” until it is calibrated: SDR on the TRX frequency with “QSY TRX → SDR”, a steady signal, then “Calibrate S-SDR to the TRX” in the SDR section; calibration kept in the browser) | first install the manufacturer's SDRplay API, then the station; `trx-sdr --list` gives the serial number; `[sdr]` and “sdr” in `[modules] run` (menu 8.1) |

> **SDR receiver: protect its input.** The SDR cannot withstand the power of your TRX. Separate antenna, or
> a switch and sequencer that ground the SDR input before any transmission: it is up to you to provide this,
> according to your equipment. The station cannot do it for you (a transmission with the transceiver microphone is only seen after
> the fact). The SDR is identified by its **serial number**: on a machine that has several, never enter the one
> of an SDR used by another application. Plug it into its own USB port, never into the transceiver's hub.
> The “USB ports” line of the COMPUTER card (dashboard, menu 1.3) tells you whether a USB bus is overloaded or whether
> the SDR is slowed down; the details and what to do are in the diagnostic (menu 6.1). A blue socket (USB 3)
> does not speed up a USB 2 SDR: it shares the 480 Mbit/s of the computer's USB 2 part.

> **Safety.** Retransmitting to third parties what the station receives (visitors, broadcast listeners)
> makes you responsible, especially outside the amateur radio bands; by default, visitors and listeners hear
> only silence outside your bands (two independent settings).

Depending on the transceiver, two features of the page may be missing: the **transceiver's HF spectrum** (only through the second
port of an Icom such as the IC-7300MK2; otherwise only the audio spectrum is shown) and the **FIL1/2/3 filter presets**
(specific to Icom).
