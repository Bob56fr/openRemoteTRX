# Datenblatt des Transceivers: Yaesu FTDX10

> **Vorbereitet, noch nicht an einem echten Gerät validiert.** Einstellungen aus dem *CAT Operation Reference Manual*
> des FTDX10 (Yaesu, Ausgabe 2308-F), der Anleitung des USB-Treibers (2205-E) und den Fähigkeiten von Hamlib. Der
> erste Operator, der die Tests aus [Teil 3](../03-integrer-et-essayer-le-trx.md) durchführt, validiert dieses
> Datenblatt: Bitte melden Sie das Ergebnis.

## Identität für die Station

| | |
|---|---|
| Hamlib-Nummer | **1042** („FTDX10“) |
| Verbindung | USB, Port „**Enhanced COM Port**“, **38400** Baud |
| PTT | über **CAT** (die Station sendet den Sendebefehl über den USB-Port) |
| Soundkarte | „USB Audio CODEC“ (Empfang und Senden) |
| Von der Station gelesen | Frequenz, Betriebsart, Filter, S-Meter, Leistung, ALC, SWR, Spannung, VFO A / B, Split, Clarifier |
| Nicht verfügbar | KW-Spektrum des Transceivers (Yaesu sendet die Bildschirmdaten nicht über CAT: nur das Audiospektrum wird angezeigt); Temperatur des Transceivers (die Temperaturschwelle der Station ist wirkungslos) |

## USB-Treiber (Windows)

1. **USB-Kabel abgezogen.** Laden Sie den Treiber „CP210x Universal Windows Driver“ herunter (Link auf der Website
   von Yaesu, oder direkt bei Silicon Labs) und entpacken Sie ihn.
2. Rechtsklick auf die Datei **`silabser.inf`** > (Windows 11: „Weitere Optionen anzeigen“) > **Installieren**.
3. Schließen Sie das USB-Kabel an, schalten Sie den Transceiver ein: Windows schließt die Installation ab (manchmal
   wird ein Neustart verlangt). Der Treiber der Soundkarte ist der von Windows, nichts zu tun.
4. Geräte-Manager > Anschlüsse (COM & LPT): zwei Zeilen „Silicon Labs Dual CP210x USB to UART Bridge“:
   **Enhanced COM Port (COMx)** für die Station, Standard COM Port (COMy) unbenutzt. Ein „!“ oder ein Kreuz an einer
   Zeile: Treiber deinstallieren und neu installieren.

Unter Debian: kein Treiber. Die stabilen Namen der Ports stehen in `/dev/serial/by-id/` (`…CP2105…-if00-port0` =
Enhanced, `…-if01-port0` = Standard); der Assistent schlägt automatisch den richtigen vor.

## Einzustellende Menüs

Pfade, wie sie im Einstellungsmenü des Transceivers erscheinen (siehe Bedienungsanleitung des FTDX10, um es zu
öffnen). Die „MODE“-Einstellungen werden **für jede Betriebsart** vorgenommen, die Sie in Telefonie nutzen wollen.

### CAT-Verbindung: OPERATION SETTING > GENERAL

| Menü | Wert | Warum |
|---|---|---|
| CAT RATE | **38400 bps** | dieselbe Baudrate wie in der Station (vom Assistenten vorgeschlagen) |
| CAT TIME OUT TIMER | **1000 msec** | vom Assistenten vorgeschlagener Wert |
| CAT RTS | **ENABLE** | Hamlib verwendet bei diesem Gerät die RTS/CTS-Flusssteuerung |
| TX TIME OUT TIMER | **3** (Minuten) | zweite Sicherheit im Transceiver selbst, über der maximalen Zeit der Station (90 s) |

(`232C RATE` und `232C TIME OUT TIMER` betreffen die RS-232C-Buchse: über USB wirkungslos.)

### Stimme über USB: RADIO SETTING > MODE SSB, MODE AM, MODE FM, MODE PSK/DATA

| Menü (in jeder Betriebsart) | Wert | Warum |
|---|---|---|
| SSB / AM / FM / DATA **MOD SOURCE** | **REAR** | die Modulation kommt von der Rückseite des Transceivers, nicht vom Frontmikrofon |
| **REAR SELECT** | **USB** | Rückseite = USB (und nicht die DATA-Buchse) |
| **RPTT SELECT** | **DAKY** | der „hintere“ PTT bleibt an der DATA-Buchse, an der nichts angeschlossen ist; **nie RTS oder DTR** |
| RPORT GAIN | anzupassen (Teil 3) | Pegel der über USB ankommenden Stimme: mit der ALC einzustellen |
| SSB / AM / FM / DATA OUT LEVEL | Werkseinstellung | nur Pegel der hinteren RTTY/DATA-Buchse: **wirkungslos auf den USB-Ton** (Test vom 2026-11-19). Empfangston zu schwach: Audiopegel in Menü **2.9** von openRemoteTRX Console |

Ohne „MOD SOURCE = REAR“ in SSB beschränkt der Assistent das Senden auf Datenbetriebsarten (DATA-U, DATA-L): Die
Seite kann dann nicht in USB / LSB senden.

> **Sicherheit: RPTT SELECT und PC KEYING.** Yaesu warnt, dass, wenn der PTT über die Leitungen des USB-Ports läuft,
> *„der Transceiver beim Hochfahren des Computers auf Senden gehen kann“*. Die Station verwendet diese Leitungen
> nicht: Lassen Sie **RPTT SELECT = DAKY** in jeder Betriebsart und **CW SETTING > MODE CW > PC KEYING = OFF**.

### Weitere empfohlene Einstellungen

| Menü | Wert | Warum |
|---|---|---|
| Taste **VOX** an der Front | **aus** | mit der Stimme über USB könnte ein Störgeräusch des PCs den Transceiver senden lassen |
| OPERATION SETTING > TX GENERAL > HF MAX POWER (und 50M, 70M, AM) | die Leistung, die Sie sich erlauben | Obergrenze des Transceivers selbst, die die Station nicht überschreiten kann |
| OPERATION SETTING > TX GENERAL > EMERGENCY FREQ TX | **DISABLE** | kein Senden auf der Notfrequenz |

## Zuordnung der Betriebsarten

| Webseite / Hamlib | Display des FTDX10 |
|---|---|
| USB / LSB | USB / LSB |
| PKTUSB / PKTLSB | DATA-U / DATA-L |
| FM / PKTFM | FM / DATA-FM |
| AM | AM |
| CW / CWR | CW-U / CW-L |

## Bei den Tests zu prüfende Punkte (Validierung dieses Datenblatts)

Im Bericht aus [Teil 3](../03-integrer-et-essayer-le-trx.md) zu vermerken:

1. Die Diagnose (Menü 6.1) findet den Transceiver; Frequenz und Betriebsart folgen, wenn Sie am VFO drehen.
2. Anzeige **VFO A / VFO B** auf der Seite, wenn Sie A/B am Transceiver drücken.
3. Senden an der Dummy-Load: Die Seite sieht Leistung, **ALC** und SWR; der ALC-Pegel bei voller Stimme (die
   Alarmschwelle der ALC wurde bei einem Yaesu noch nicht ermittelt).
4. Split am Transceiver aktiviert: Die Seite zeigt ihn an, das Senden geht auf der richtigen Frequenz hinaus.
5. Senden mit dem Mikrofon des Transceivers: Die Seite zeigt „Operator vor Ort“ an und sperrt den Fern-PTT.
6. Kein Wechsel auf Senden beim Hochfahren des PCs oder beim Anschließen des Kabels.
