# 6. An unattended station

A remotely controlled station runs most of the time with nobody next to it. This part prepares for that.

## 6.1 Alerts on your phone (ntfy)

The station's supervisor can send you notifications: transmission cut for safety, failure, safety lockout, memory
or disk almost full, link dropout, and a silent “Station in service” message every hour (if it stops arriving, the
station or its connection has failed).

1. Install the **ntfy** app on the phone.
2. Choose a **long topic name that is impossible to guess** (for example 20 random letters and digits): on the public
   ntfy.sh server, anyone who knows the name reads the messages.
3. Subscribe to this topic in the ntfy app.
4. On the station, menu **3.5** “Alerts on the phone”: choice 1, paste the address `https://ntfy.sh/<your-topic>`,
   save, accept the restart. The screen never shows the full address.
5. Check: choice 4, “Send a test alert now”; the phone must ring at once (code ORT-8025).
   After that, the “Station in service” message arrives every hour (choice 3 to change this rhythm).

Each alert carries an “ORT-NNNN” code with a link to its explanation (part 8). Two alerts arrive at restart after a
shutdown that was not clean: **ORT-8030** (Debian, Raspberry Pi: the machine stopped abruptly, power cut or crash)
and **ORT-8031** (the supervisor alone stopped); each gives the time of the last sign of life. A normal stop
(menu 1.2, PC shutdown) sends nothing.

## 6.2 The safety lockout

After repeated failures that restarts did not fix, the supervisor **puts the station in safety lockout**:
transceiver in receive, access cut, alert sent. The safety lockout **survives restarts**: find the cause
(menus 6.1 and 6.2), then lift it with menu **1.4**.

## 6.3 After a power cut

| Item | To set |
|---|---|
| PC | in the BIOS / UEFI: “Restore on AC power loss” = **Power On** (the name varies with the motherboard) |
| Raspberry Pi | nothing: it restarts as soon as power returns |
| Debian or Raspberry Pi station | nothing: it starts with the machine, without opening a session |
| Windows station | it starts at **session login**: without automatic login of your session, it stays stopped |
| Transceiver | most transceivers do **not** power on by themselves. The station can power it on through CAT (menu **2.8**, off by default, with a power off / power on test): your connection from the page or the app powers it on |
| Box | powers on by itself; check that the VPN does too |

A **UPS** for the PC, the box and the transceiver's power supply avoids most of these cases.

## 6.4 Hardware protection

- **Lightning**: a station away from any human presence is exposed. Lightning arrester on the antenna cable, and
  antenna grounded or disconnected when a storm is forecast.
- **Power**: the transceiver's ceiling (HF MAX POWER, part 1) remains the last barrier.
- **Transceiver timer** (TX TIME OUT TIMER): set to 3 min, it cuts even if everything else has failed.
- **Temperature**: the supervisor watches the PC's processor and alerts when it stays above 70 °C for one minute (a
  peak of a few seconds does not count); the alert says which programs were heating. On Debian and on a Pi, the
  history of the last 24 h (one reading every 10 s) is attached to the troubleshooting report (menu 6.3). On a Pi, a
  fan is essential. The transceiver's temperature cannot be read by the station on the transceivers tested
  (IC-7300MK2, FTDX10): proper ventilation around the transceiver.
- **Local operator**: if someone uses the transceiver on site, remote transmission is blocked during their
  transmission and then for 2 minutes; the station never cuts them for this reason. A transmission with the
  microphone is cut by the absolute TOT (135 s), unless the operator touched the transceiver (volume, frequency, mode,
  leaving DATA mode…) in the 2 minutes before speaking or while speaking: the station knows they are present and lets
  them speak for up to 5 minutes (`local_tx_max_s`), with a simple alert in between. The transceiver timer, if set
  shorter, cuts first. These settings are in menu **3.4** “Operator on site”: keep “shared station”; otherwise, a
  microphone held down leads to the safety lockout.
