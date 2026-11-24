# 10. Summary: where are you?

Tick as you go. On the guide's web page, boxes are ticked online and stay ticked in your
browser; on GitHub, print this page or copy the list.

## 0. Before you start

- [ ] Remote operation conditions checked for my licence
- [ ] Dummy load available for the tests
- [ ] System chosen (Debian recommended, Raspberry Pi or Windows) and package downloaded

## 1. Prepare the transceiver

- [ ] Manufacturer's USB driver installed before plugging in the cable (Windows)
- [ ] Transceiver command port identified (transceiver sheet)
- [ ] Transceiver CAT speed noted, menus of the transceiver sheet set
- [ ] Voice through USB set in each mode used
- [ ] No RTS / DTR line of the USB port keys the transmitter
- [ ] VOX off, transceiver transmit timer at 3 min, maximum power set
- [ ] Transceiver sound card removed from the PC's default sound

## 2. Install the station

- [ ] Software installed (install.sh or installer.cmd)
- [ ] Session reopened (Debian, Raspberry Pi); Private network profile and sleep disabled (Windows)
- [ ] Raspberry Pi: official power supply, fan, `throttled=0x0`

## 3. Integrate the TRX and test it

- [ ] Wizard completed (model of my transceiver, command port, PTT by CAT, bands of my licence)
- [ ] Diagnostic without failure
- [ ] Guided test in receive only passed
- [ ] Guided test with transmission passed on a dummy load
- [ ] Station started, page open, modulation set with the ALC (transceiver USB input level)
- [ ] Test 1: STOP cuts the transmission
- [ ] Test 2: cut after 90 s, warning 10 s before
- [ ] Test 3: link cut during transmission, back to receive
- [ ] Test 4: screen locked during transmission, back to receive
- [ ] Test 5: transmission refused outside my bands
- [ ] Test 6: transmission with the transceiver microphone, remote PTT blocked
- [ ] Test 7: STOP TX from the dashboard
- [ ] Test 8: station stopped during transmission
- [ ] Test 9: no transmission when the PC (or the Pi) starts
- [ ] Test results reported, if my transceiver is not yet validated (issue “<my transceiver>: commissioning tests”)

## 4. Use on the local network

- [ ] IP address reserved for the station PC in the router
- [ ] Web page opened over https, certificate accepted, microphone allowed
- [ ] One account per device (menu 4.3), long passwords
- [ ] Android application paired with the QR code (menu 4.1), transmission test and STOP

## 5. Use remotely

- [ ] Choice made: VPN (recommended) or open port
- [ ] One VPN profile per device
- [ ] From 4G: page, received audio, transmission on a dummy load, STOP
- [ ] From 4G: airplane mode during transmission, back to receive

## 6. Unattended station

- [ ] ntfy alerts received (long and secret topic), “Station in service” message seen
- [ ] PC set to power on again after a power cut (a Pi does it by itself)
- [ ] UPS, surge protector, transceiver ventilation
- [ ] I know how to reactivate the station after a safety lockout (menu 1.4) once the cause is found

## 7. Day-to-day operation

- [ ] I know how to start, stop and monitor the station
- [ ] I know how to update and go back to the previous version
- [ ] Configuration and certificate backed up elsewhere
- [ ] Transceiver profile saved (menu 2.3)

## Station in service

- [ ] First transmission on the antenna, in my bands, with identification
