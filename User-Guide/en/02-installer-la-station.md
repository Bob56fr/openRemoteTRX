# 2. Install the station

Installation never controls the transceiver: it can stay on and connected. Choose your system in the tabs below; the
choice applies to the whole page. At the end, **openRemoteTRX Console** opens and offers the configuration wizard:
that is part 3.

<!-- onglets -->
#### Debian

**Debian 12 or 13, with a desktop.**

1. Download `trx-remote-debian-X.Y.Z.zip` (part 0) into **Downloads**, right-click > “Extract Here”.
2. In the resulting folder: right-click in an empty area > “Open in Terminal”, then:

   ```
   sudo bash install.sh
   ```

   Your session password is requested (nothing is displayed while you type: this is normal). The script installs
   Hamlib, Python, the modules, the service account and the station services.
3. At the end, **log out and log back in** (your account's permissions change).
4. Open **openRemoteTRX Console** from the applications menu (or type `trx-console` in a terminal).

**Hamlib and recent transceivers.** Debian 13 ships Hamlib 4.6, which does not know recent transceivers
(IC-7300MK2…): `install.sh` installs version 4.7 from Debian's **official backports** by itself. On Debian 12, if
your transceiver is missing from `rigctl -l`, the installation tells you: then run `sudo bash compiler-hamlib.sh` in
the same folder (compiles the latest Hamlib, 10 to 30 minutes).

**Without a desktop (server)**, everything is done over SSH: copy the zip, then

```
unzip -q trx-remote-debian-*.zip && cd trx-remote-debian-*/ && sudo bash install.sh
```

close the SSH connection, reconnect and type `trx-console`.

#### Raspberry Pi

**Raspberry Pi 4 or 5, Raspberry Pi OS 64-bit.** The Pi uses the **same package** as Debian.

> **The Pi as a station.** Already in service with a beta tester, but its load has not yet been measured with
> everything running (SDR receiver, FreeDV, several visitors): start with the basic functions. A Pi 3 or older is
> too slow for live audio.

**The hardware.**

| Item | Advice |
|---|---|
| The Pi | Pi 4 with **4 GB** (2 GB minimum), or Pi 5 |
| Power supply | the **official** unit (Pi 4: USB-C 5.1 V 3 A; Pi 5: 5 V 5 A). A phone charger causes undervoltage: the Pi slows down and the transceiver's USB drops out |
| Cooling | heatsink with fan, or ventilated case: without it, the Pi slows down around 80 °C |
| Storage | 32 GB “High Endurance” class A2 SD card, or better an **SSD over USB 3** (the Pi boots from it, and it lasts longer than a card that writes day and night) |
| Network | Ethernet cable recommended; Wi-Fi works, with more audio dropouts |

**1. Prepare the card**, on your PC, with **Raspberry Pi Imager** (raspberrypi.com/software):

1. Device: your Pi model. Operating system: **Raspberry Pi OS (64-bit)** if a screen will stay connected; otherwise
   *Raspberry Pi OS (other)* > **Raspberry Pi OS Lite (64-bit)**, without a desktop, everything will be done from
   your PC.
2. Customisation, **before** writing the card: a name (for example `trx-pi`), an account and its **password**
   (required for installing), the time zone and keyboard, Wi-Fi only if there is no cable, and **SSH enabled**
   (preferably with a public key).
3. Write the card, put it in the Pi, connect the network, the transceiver, then the power supply. The first boot
   takes 2 to 3 minutes (the Pi restarts once by itself).
4. Find the Pi's address in your router's list of devices, and **reserve it** (DHCP reservation, part 4.1).

**2. Update the system**, in a terminal on the Pi (with a desktop) or from your PC (without a desktop:
`ssh -l <account> <pi-address>`):

```
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

**3. Install the station.**

- **With a desktop**: exactly as on Debian (Debian tab): zip downloaded and extracted, `sudo bash install.sh` in a
  terminal opened in the folder, then log out and log back in.
- **Without a desktop**, from your PC (PowerShell on Windows, terminal on Linux or macOS), in the folder of the
  downloaded zip:

  ```
  scp -o User=<account> trx-remote-debian-X.Y.Z.zip <pi-address>:
  ssh -t -l <account> <pi-address>
  ```

  then, on the Pi:

  ```
  sudo apt install -y unzip
  unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh
  ```

  At the end, type `exit` and reconnect (`ssh -t -l <account> <pi-address>`): your account's permissions have
  changed. Then `trx-console`.

**What the installation does in addition on a Pi.**

- It shows the model and reports a Pi that is too old, too little memory or **undervoltage** (power supply too
  weak): fix it before going further.
- Raspberry Pi OS 13 ships Hamlib 4.6: it installs 4.7 from Debian's official backports (recent transceivers such as
  the IC-7300MK2). On Raspberry Pi OS 12, if your transceiver is missing from `rigctl -l`:
  `sudo bash compiler-hamlib.sh` (10 to 30 minutes on a Pi).
- It enables the Pi's **hardware watchdog**: if the system freezes for more than 15 seconds, the Pi restarts by
  itself, and the station comes back in receive.
- With a desktop, it adds the font for openRemoteTRX Console's icons.

**4. Check the power supply and the temperature**, after a few minutes of running:

```
vcgencmd get_throttled; vcgencmd measure_temp
```

Expected: `throttled=0x0` and less than 70 °C. Any other value of `throttled` = power supply too weak or overheating:
change the power supply or add a fan. Once the station is running, its supervisor will send you an alert (part 6) if
the Pi is slowed down, or if the memory or the disk fill up.

<details>
<summary>Working without a screen day to day</summary>

- **openRemoteTRX Console over SSH**: `ssh -t -l <account> <pi-address> trx-console` (the `-t` is essential: the
  console asks questions). Windows Terminal displays the frames, colours and the QR code of menu 4.1 correctly.
- **More comfortable: the console in the browser.** Once, menu **4.6** (part 7.5); then
  `https://<pi-address>:8444/` from the PC, the tablet or the phone, without SSH.
- **Dashboard**: `ssh -t -l <account> <pi-address> trx-monitor`, or the vital signs dashboard in the browser
  (part 7.1).
- **Shut down the Pi**: `sudo poweroff`, then wait until the green LED stops blinking before cutting the power (a
  sudden power cut can damage the SD card).

</details>

#### Windows

**Windows 10 or 11, 64-bit.**

1. Install **Hamlib 64-bit** (`hamlib-w64-X.Y.Z.exe`, version **4.7** or later: recent transceivers such as the
   IC-7300MK2 do not exist before) from https://github.com/Hamlib/Hamlib/releases, in the suggested folder.
2. Copy `trx-remote-windows-X.Y.Z.zip` to the PC. Right-click > Properties > tick **Unblock** > OK.
3. Right-click > Extract All, then double-click **`installer.cmd`**. If Windows shows “Windows protected your PC”:
   More info > Run anyway.
4. Accept the administrator request and answer the questions (Python is installed if it is missing, with your
   consent).
5. Essential Windows settings:
   - home network set to the **Private** profile (the firewall only opens the station on private networks);
   - **sleep and hibernation disabled** (Settings > System > Power);
   - *Settings > Privacy > Microphone*: access allowed for desktop apps (otherwise the audio received from the
     transceiver is silence);
   - transceiver sound card (*Settings > System > Sound*, the transceiver's “Speakers” output): **volume at 100**,
     **audio enhancements disabled**, format 16 bit 48000 Hz; the transmit level is set on the transceiver (Icom:
     USB MOD Level). A reduced volume (38 seen on one PC) gives a transmission with no power. Its name (“2- USB Audio
     Device”…) changes if the transceiver cable moves to another USB socket: then redo menu 2.6.

The full notice (`notice-windows.html`) is in the package.

**openRemoteTRX Console on Windows.** The installation creates **a single shortcut**: Start menu >
**openRemoteTRX**. It opens openRemoteTRX Console, with the same numbered menus as on Debian: this guide applies as
is (1.1 start, 2.1 configuration, 6.1 diagnostic…). Differences:

- **Updates** (menus 7.1 to 7.3): on Windows, extract the new zip and run its `installer.cmd`; the configuration is
  kept. Going back: run `installer.cmd` of the old version again.
- **Indicator next to the clock**: menu 8.4 (start it, or start it at each session login).
- **Uninstall**: Settings > Apps > **openRemoteTRX** > Uninstall (the configuration is kept unless you ask to erase
  it).
- The configuration is in `C:\ProgramData\trx-remote\station.toml`; the commands (`trx-console`, `trx-setup`,
  `trx-monitor`…) can also be run in a terminal opened **after** the installation.
<!-- /onglets -->
