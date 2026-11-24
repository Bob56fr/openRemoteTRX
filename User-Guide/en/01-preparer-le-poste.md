# 1. Prepare the transceiver

Station **switched off**, nothing connected: now is the time to set up the transceiver. The details of your
transceiver's menus are in its sheet ([Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md)); for
another transceiver, see its manual and the “Depending on your brand” table of the [quick start](demarrage-rapide.md).
This part tells you in which order to do things.

## 1.1 Install the USB driver (Windows only)

On Windows, the transceiver's USB driver (the one from its manufacturer: “Icom USB Driver”, Silicon Labs CP210x for
Yaesu…) is installed **before** you plug in the USB cable; otherwise Windows may install the wrong driver. The name,
the minimum version and the procedure are in the transceiver sheet, “USB driver”, or else on the manufacturer's
website.

On Debian and on a Raspberry Pi, there is nothing to install: the kernel recognises the transceiver by itself.

## 1.2 Connect

1. Antenna disconnected, **dummy load** on the antenna socket in use.
2. USB cable between the transceiver and the PC.
3. Switch the transceiver on (long press on ON/OFF).

The PC now sees one or two **serial ports** and a **sound card**. The transceiver sheet tells you which one is used
for control (IC-7300MK2: the first one, the second one is used for the HF spectrum; FTDX10: the “Enhanced COM Port”,
the “Standard” one is not used).

<!-- onglets -->
#### Debian

Nothing to note: the wizard finds the right port by itself. To see it: `ls -l /dev/serial/by-id/` in a terminal (one
stable name per port, which does not change from one USB socket to another).

#### Raspberry Pi

As on Debian. Plug the transceiver cable **directly** into a USB port of the Pi (the blue USB 3 ports work too); use a
hub only if it has its own power supply: the Pi does not supply enough current to several devices.

#### Windows

Device Manager > Ports (COM & LPT): note the COM number of the control port.
<!-- /onglets -->

## 1.3 Set the transceiver menus

Set the menus listed in your transceiver's sheet, section “Menus to set” (otherwise, its manual). They are
essential:

- **CAT speed** identical to the station's (chosen in the wizard);
- **voice over USB**: otherwise the transceiver modulates with its own microphone, that is, the noise of the room. On
  an Icom (IC-7300MK2): MENU > SET > Connectors > MOD Input > **DATA MOD = USB** (the station only transmits in data
  mode); the transceiver accepts the USB input only in DATA MOD **or** DATA OFF MOD. With the second port set up, the
  station checks it at each connection and warns you if it is not on USB;
- **no RTS/DTR line** for PTT or CW: otherwise the transceiver may go into transmit when the PC starts;
- **VOX off**: a VOX that is on makes the transceiver transmit on a noise in the room, without any command. The
  station checks it each time an operator connects and **turns it off** if it is on (message in the page log, code
  ORT-5034). On some transceivers it stays on in one mode while it is off in another (seen on the IC-7300MK2: off in
  data mode, still on in voice);
- **built-in antenna tuner** (if the antenna goes through it): tuning must start by itself when transmission is keyed
  on a new frequency. On the IC-7300MK2: MENU > SET > Function > Tuner, **[TUNER] Switch = Auto** (tuner state stored
  per band) and **PTT Start = ON**. Answer “yes” to the wizard's tuner question: the station will check these
  settings at each connection and warn you if they are wrong (it never changes them). Outside the amateur bands, the
  transceiver does not guarantee tuning on PTT. During a transmission, if the SWR exceeds 2 for more than one second,
  the page shows a red banner and beeps (it does not cut);
- **transceiver transmit timer** (TX TIME OUT TIMER): a second safety, independent of the station. Set it (3 min
  recommended): if the station, the network or the PC fails during a transmission, this is what cuts. For a
  transceiver whose reading is qualified (IC-7300MK2), the station reads it at each connection and warns you if it is
  OFF; for the others, it cannot check it.

> **Safety.** An extra safety costs nothing: also set a reasonable **maximum power** in the transceiver (HF MAX
> POWER). The station cannot exceed it, whatever happens.

## 1.4 PC sound

The transceiver's sound card must **never** be the PC's default sound device, otherwise desktop sounds go to the
transceiver (and the desktop occupies the card):

<!-- onglets -->
#### Debian

*Settings > Sound*: the PC speakers as output, its microphone as input.

#### Raspberry Pi

Without a desktop (Raspberry Pi OS Lite): nothing to do, no program takes the transceiver's card. With a desktop: as
on Debian, in the sound settings of the top bar. The Pi's own sound card (“Headphones”, “HDMI”) is not used by the
station.

#### Windows

*Settings > System > Sound*: the PC speakers as output, its microphone as input; in “More sound settings”, the
transceiver's card is neither “Default Device” nor “Default Communication Device”; sound scheme “No Sounds”. The
details are in the Windows notice included in the package.
<!-- /onglets -->
