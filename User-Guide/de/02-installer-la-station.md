# 2. Die Station installieren

Die Installation steuert den Transceiver nie: Er kann eingeschaltet und angeschlossen bleiben. Wählen Sie Ihr System
in den Reitern unten; die Wahl gilt für die ganze Seite. Am Ende öffnet sich **openRemoteTRX Console** und schlägt
den Konfigurationsassistenten vor: das ist Teil 3.

<!-- onglets -->
#### Debian

**Debian 12 oder 13, mit Desktop.**

1. Laden Sie `trx-remote-debian-X.Y.Z.zip` (Teil 0) nach **Downloads** herunter, Rechtsklick > „Hier entpacken“.
2. Im entstandenen Ordner: Rechtsklick auf eine leere Fläche > „In Terminal öffnen“, dann:

   ```
   sudo bash install.sh
   ```

   Ihr Sitzungspasswort wird abgefragt (bei der Eingabe erscheint nichts: das ist normal). Das Skript installiert
   Hamlib, Python, die Module, das Dienstkonto und die Dienste der Station.
3. Am Ende **melden Sie sich ab und wieder an** (die Rechte Ihres Kontos ändern sich).
4. Öffnen Sie **openRemoteTRX Console** aus dem Anwendungsmenü (oder geben Sie `trx-console` in einem Terminal ein).

**Hamlib und neuere Transceiver.** Debian 13 liefert Hamlib 4.6, das neuere Transceiver nicht kennt (IC-7300MK2…):
`install.sh` installiert selbst die Version 4.7 aus den **offiziellen Backports** von Debian. Fehlt Ihr Transceiver
unter Debian 12 in `rigctl -l`, sagt Ihnen die Installation das: Starten Sie dann `sudo bash compiler-hamlib.sh` im
selben Ordner (Kompilieren des neuesten Hamlib, 10 bis 30 Minuten).

**Ohne Desktop (Server)** geschieht alles per SSH: Kopieren Sie das Zip, dann

```
unzip -q trx-remote-debian-*.zip && cd trx-remote-debian-*/ && sudo bash install.sh
```

schließen Sie die SSH-Verbindung, melden Sie sich neu an und geben Sie `trx-console` ein.

#### Raspberry Pi

**Raspberry Pi 4 oder 5, Raspberry Pi OS 64 Bit.** Der Pi verwendet das **gleiche Paket** wie Debian.

> **Der Pi als Station.** Bereits bei einem Betatester in Betrieb, aber seine Last ist mit allem eingeschaltet noch
> nicht gemessen (SDR-Empfänger, FreeDV, mehrere Besucher): Beginnen Sie mit den Grundfunktionen. Ein Pi 3 oder
> älter ist für Ton in Echtzeit zu langsam.

**Die Hardware.**

| Element | Empfehlung |
|---|---|
| Der Pi | Pi 4 mit **4 GB** (mindestens 2 GB) oder Pi 5 |
| Netzteil | das **offizielle** Netzteil (Pi 4: USB-C 5,1 V 3 A; Pi 5: 5 V 5 A). Ein Telefon-Ladegerät verursacht Unterspannungen: Der Pi wird langsamer und das USB des Transceivers bricht ab |
| Kühlung | Kühlkörper mit Lüfter oder belüftetes Gehäuse: ohne sie drosselt der Pi bei etwa 80 °C |
| Speicher | SD-Karte 32 GB „High Endurance“ Klasse A2, oder besser eine **SSD an USB 3** (der Pi startet davon, und sie hält länger als eine Karte, die Tag und Nacht schreibt) |
| Netzwerk | Ethernet-Kabel empfohlen; WLAN funktioniert, mit mehr Tonaussetzern |

**1. Die Karte vorbereiten**, auf Ihrem PC, mit **Raspberry Pi Imager** (raspberrypi.com/software):

1. Gerät: Ihr Pi-Modell. System: **Raspberry Pi OS (64-bit)**, wenn ein Bildschirm angeschlossen bleibt; sonst
   *Raspberry Pi OS (other)* > **Raspberry Pi OS Lite (64-bit)**, ohne Desktop, alles geschieht dann von Ihrem PC aus.
2. Anpassung, **bevor** Sie die Karte schreiben: ein Name (zum Beispiel `trx-pi`), ein Konto und sein **Passwort**
   (unverzichtbar für die Installation), Zeitzone und Tastatur, WLAN nur ohne Kabel und **SSH aktiviert** (am besten
   mit öffentlichem Schlüssel).
3. Schreiben Sie die Karte, stecken Sie sie in den Pi, schließen Sie Netzwerk, Transceiver und dann das Netzteil an.
   Der erste Start dauert 2 bis 3 Minuten (der Pi startet einmal von selbst neu).
4. Suchen Sie die Adresse des Pi in der Geräteliste Ihres Routers und **reservieren Sie sie** (DHCP-Reservierung,
   Teil 4.1).

**2. Das System aktualisieren**, in einem Terminal des Pi (mit Desktop) oder von Ihrem PC aus (ohne Desktop:
`ssh -l <konto> <pi-adresse>`):

```
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

**3. Die Station installieren.**

- **Mit Desktop**: genau wie unter Debian (Reiter Debian): Zip heruntergeladen und entpackt, `sudo bash install.sh`
  in einem im Ordner geöffneten Terminal, dann ab- und wieder anmelden.
- **Ohne Desktop**, von Ihrem PC aus (PowerShell unter Windows, Terminal unter Linux oder macOS), im Ordner des
  heruntergeladenen Zips:

  ```
  scp -o User=<konto> trx-remote-debian-X.Y.Z.zip <pi-adresse>:
  ssh -t -l <konto> <pi-adresse>
  ```

  dann auf dem Pi:

  ```
  sudo apt install -y unzip
  unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh
  ```

  Geben Sie am Ende `exit` ein und melden Sie sich neu an (`ssh -t -l <konto> <pi-adresse>`): Die Rechte Ihres Kontos
  haben sich geändert. Dann `trx-console`.

**Was die Installation auf einem Pi zusätzlich tut.**

- Sie zeigt das Modell an und meldet einen zu alten Pi, zu wenig Speicher oder eine **Unterspannung** (zu schwaches
  Netzteil): Beheben Sie das, bevor Sie weitermachen.
- Raspberry Pi OS 13 liefert Hamlib 4.6: Sie installiert die 4.7 aus den offiziellen Backports von Debian (neuere
  Transceiver wie der IC-7300MK2). Fehlt Ihr Transceiver unter Raspberry Pi OS 12 in `rigctl -l`:
  `sudo bash compiler-hamlib.sh` (10 bis 30 Minuten auf einem Pi).
- Sie schaltet den **Hardware-Watchdog** des Pi ein: Hängt das System länger als 15 Sekunden, startet der Pi von
  selbst neu, und die Station läuft wieder auf Empfang an.
- Mit Desktop fügt sie die Schriftart für die Symbole von openRemoteTRX Console hinzu.

**4. Netzteil und Temperatur prüfen**, nach einigen Minuten Betrieb:

```
vcgencmd get_throttled; vcgencmd measure_temp
```

Erwartet: `throttled=0x0` und weniger als 70 °C. Jeder andere Wert von `throttled` = Netzteil zu schwach oder
Überhitzung: Tauschen Sie das Netzteil oder fügen Sie einen Lüfter hinzu. Sobald die Station läuft, schickt Ihnen ihr
Supervisor einen Alarm (Teil 6), wenn der Pi gedrosselt ist oder sich Speicher oder Festplatte füllen.

<details>
<summary>Im Alltag ohne Bildschirm arbeiten</summary>

- **openRemoteTRX Console per SSH**: `ssh -t -l <konto> <pi-adresse> trx-console` (das `-t` ist unverzichtbar: Die
  Konsole stellt Fragen). Windows Terminal zeigt Rahmen, Farben und den QR-Code aus Menü 4.1 gut an.
- **Bequemer: die Konsole im Browser.** Einmal Menü **4.6** (Teil 7.5); danach `https://<pi-adresse>:8444/` vom PC,
  Tablet oder Telefon aus, ohne SSH.
- **Dashboard**: `ssh -t -l <konto> <pi-adresse> trx-monitor`, oder das Vitalwerte-Dashboard im Browser (Teil 7.1).
- **Den Pi ausschalten**: `sudo poweroff`, dann warten Sie, bis die grüne LED aufhört zu blinken, bevor Sie den Strom
  trennen (ein harter Stromausfall kann die SD-Karte beschädigen).

</details>

#### Windows

**Windows 10 oder 11, 64 Bit.**

1. Installieren Sie **Hamlib 64 Bit** (`hamlib-w64-X.Y.Z.exe`, Version **4.7** oder neuer: neuere Transceiver wie der
   IC-7300MK2 gibt es davor nicht) von https://github.com/Hamlib/Hamlib/releases, im vorgeschlagenen Ordner.
2. Kopieren Sie `trx-remote-windows-X.Y.Z.zip` auf den PC. Rechtsklick > Eigenschaften > **Zulassen** ankreuzen > OK.
3. Rechtsklick > Alle extrahieren, dann Doppelklick auf **`installer.cmd`**. Zeigt Windows „Der Computer wurde durch
   Windows geschützt“: Weitere Informationen > Trotzdem ausführen.
4. Bestätigen Sie die Administratoranfrage und beantworten Sie die Fragen (Python wird installiert, falls es fehlt,
   mit Ihrer Zustimmung).
5. Unverzichtbare Windows-Einstellungen:
   - Heimnetz im Profil **Privat** (die Firewall öffnet die Station nur in privaten Netzwerken);
   - **Energiesparmodus und Ruhezustand deaktiviert** (Einstellungen > System > Energie);
   - *Einstellungen > Datenschutz > Mikrofon*: Zugriff für Desktop-Apps erlaubt (sonst ist der empfangene Ton des
     Transceivers Stille);
   - Soundkarte des Transceivers (*Einstellungen > System > Sound*, Ausgabe „Lautsprecher“ des Transceivers):
     **Lautstärke 100**, **Audioverbesserungen deaktiviert**, Format 16 Bit 48000 Hz; der Sendepegel wird am
     Transceiver dosiert (Icom: USB MOD Level). Eine reduzierte Lautstärke (38 auf einem PC gesehen) ergibt ein
     Senden ohne Leistung. Ihr Name („2- USB Audio Device“…) ändert sich, wenn das Kabel des Transceivers an eine
     andere USB-Buchse kommt: Dann Menü 2.6 wiederholen.

Die vollständige Anleitung (`notice-windows.html`) liegt im Paket.

**openRemoteTRX Console unter Windows.** Die Installation legt **eine einzige Verknüpfung** an: Startmenü >
**openRemoteTRX**. Sie öffnet openRemoteTRX Console, mit denselben nummerierten Menüs wie unter Debian: Dieses
Handbuch gilt unverändert (1.1 starten, 2.1 Konfiguration, 6.1 Diagnose…). Unterschiede:

- **Aktualisierungen** (Menüs 7.1 bis 7.3): Unter Windows entpacken Sie das neue Zip und starten sein
  `installer.cmd`; die Konfiguration bleibt erhalten. Zurück: Starten Sie `installer.cmd` der alten Version.
- **Anzeige neben der Uhr**: Menü 8.4 (starten oder bei jeder Anmeldung starten).
- **Deinstallieren**: Einstellungen > Apps > **openRemoteTRX** > Deinstallieren (die Konfiguration bleibt erhalten,
  außer Sie verlangen, sie zu löschen).
- Die Konfiguration liegt in `C:\ProgramData\trx-remote\station.toml`; die Befehle (`trx-console`, `trx-setup`,
  `trx-monitor`…) lassen sich auch in einem Terminal starten, das **nach** der Installation geöffnet wurde.
<!-- /onglets -->
