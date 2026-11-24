# Transceiver sheet: Yaesu FTDX10

> **Prepared, not yet validated on a real transceiver.** Settings taken from the FTDX10 *CAT Operation Reference Manual*
> (Yaesu, edition 2308-F), from the USB driver instructions (2205-E) and from Hamlib's capabilities. The first operator
> who runs the tests of [part 3](../03-integrer-et-essayer-le-trx.md) validates this sheet: thank you for
> reporting the result.

## Identity for the station

| | |
|---|---|
| Hamlib number | **1042** (“FTDX10”) |
| Link | USB, “**Enhanced COM Port**”, **38400** baud |
| PTT | by **CAT** (the station sends the transmit command through the USB port) |
| Sound card | “USB Audio CODEC” (receive and transmit) |
| Read by the station | frequency, mode, filters, S-meter, power, ALC, SWR, voltage, VFO A / B, split, clarifier |
| Not available | transceiver HF spectrum (Yaesu does not send the screen data over CAT: only the audio spectrum is shown); transceiver temperature (the station's temperature threshold has no effect) |

## USB driver (Windows)

1. **USB cable unplugged.** Download the “CP210x Universal Windows Driver” (link on the Yaesu website, or
   directly from Silicon Labs) and unzip it.
2. Right-click the **`silabser.inf`** file > (Windows 11: “Show more options”) > **Install**.
3. Plug in the USB cable, switch on the transceiver: Windows finishes the installation (sometimes asks for a restart). The
   sound card driver is the Windows one, nothing to do.
4. Device Manager > Ports (COM & LPT): two lines “Silicon Labs Dual CP210x USB to UART Bridge”:
   **Enhanced COM Port (COMx)** for the station, Standard COM Port (COMy) unused. A “!” or a cross on a
   line: uninstall then reinstall the driver.

On Debian: no driver. The stable port names are in `/dev/serial/by-id/` (`…CP2105…-if00-port0` =
Enhanced, `…-if01-port0` = Standard); the wizard offers the right one by default.

## Menus to set

Paths as they appear in the transceiver's settings menu (see the FTDX10 operating manual to
open it). The “MODE” settings are made **for each mode** you want to use in phone.

### CAT link: OPERATION SETTING > GENERAL

| Menu | Value | Why |
|---|---|---|
| CAT RATE | **38400 bps** | same speed as in the station (offered by the wizard) |
| CAT TIME OUT TIMER | **1000 msec** | value offered by the wizard |
| CAT RTS | **ENABLE** | Hamlib uses RTS/CTS flow control on this transceiver |
| TX TIME OUT TIMER | **3** (minutes) | second safety of the transceiver itself, beyond the station's maximum time (90 s) |

(`232C RATE` and `232C TIME OUT TIMER` concern the RS-232C socket: no effect over USB.)

### Voice through USB: RADIO SETTING > MODE SSB, MODE AM, MODE FM, MODE PSK/DATA

| Menu (in each mode) | Value | Why |
|---|---|---|
| SSB / AM / FM / DATA **MOD SOURCE** | **REAR** | the modulation comes from the rear of the transceiver, not from the front microphone |
| **REAR SELECT** | **USB** | the rear = USB (and not the DATA socket) |
| **RPTT SELECT** | **DAKY** | the “rear” PTT stays on the DATA socket, where nothing is plugged in; **never RTS or DTR** |
| RPORT GAIN | to adjust (part 3) | level of the voice arriving through USB: to set with the ALC |
| SSB / AM / FM / DATA OUT LEVEL | factory value | level of the rear RTTY/DATA socket only: **no effect on the USB audio** (test of 2026-11-19). Received audio too low: gain of menu **2.9** of openRemoteTRX Console |

Without “MOD SOURCE = REAR” in SSB, the wizard limits transmission to data modes (DATA-U, DATA-L): the page will
not be able to transmit in USB / LSB.

> **Safety: RPTT SELECT and PC KEYING.** Yaesu warns that, when the PTT goes through the USB port lines, *“the
> transceiver may go into transmission when the computer starts”*. The station does not use these lines: leave
> **RPTT SELECT = DAKY** in each mode and **CW SETTING > MODE CW > PC KEYING = OFF**.

### Other recommended settings

| Menu | Value | Why |
|---|---|---|
| Front panel **VOX** key | **off** | with the voice through USB, a stray sound from the PC could make the transceiver transmit |
| OPERATION SETTING > TX GENERAL > HF MAX POWER (and 50M, 70M, AM) | the power you allow yourself | ceiling of the transceiver itself, which the station cannot exceed |
| OPERATION SETTING > TX GENERAL > EMERGENCY FREQ TX | **DISABLE** | no transmission on the emergency frequency |

## Mode mapping

| Web page / Hamlib | FTDX10 screen |
|---|---|
| USB / LSB | USB / LSB |
| PKTUSB / PKTLSB | DATA-U / DATA-L |
| FM / PKTFM | FM / DATA-FM |
| AM | AM |
| CW / CWR | CW-U / CW-L |

## Points to check during the tests (validation of this sheet)

To note in the report of [part 3](../03-integrer-et-essayer-le-trx.md):

1. The diagnostic (menu 6.1) finds the transceiver; frequency and mode follow when you turn the VFO.
2. **VFO A / VFO B** indicator in the page when you press A/B on the transceiver.
3. Transmission on a dummy load: the page sees power, **ALC** and SWR; the ALC level at full voice (the ALC
   alert threshold has not yet been measured on a Yaesu).
4. Split enabled on the transceiver: the page shows it, the transmission goes out on the right frequency.
5. Transmission with the transceiver microphone: the page shows “local operator” and blocks the remote PTT.
6. No transmission when the PC starts or when the cable is plugged in.
