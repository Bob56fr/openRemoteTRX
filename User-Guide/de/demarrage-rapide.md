# Schnellstart

Für Ungeduldige: Ihr Transceiver im Browser in einer Viertelstunde. Der Rest des Handbuchs erklärt jeden Schritt im
Detail; kehren Sie beim ersten Problem dorthin zurück.

## Sie brauchen

- einen Transceiver, den Hamlib kennt, mit dem PC verbunden: bei den meisten neueren Geräten ein USB-Kabel (Steuerung
  und Ton), sonst ein Interface wie Digirig oder SignaLink;
- einen PC mit **Debian 12 oder 13** oder **Windows 10 / 11** 64 Bit, oder einen **Raspberry Pi 4 oder 5**
  (Raspberry Pi OS 64 Bit, offizielles Netzteil), dauerhaft eingeschaltet in der Nähe des Transceivers, mit dem
  Router verbunden;
- eine **Dummy-Load** für das erste Senden;
- ein Telefon oder einen PC mit einem aktuellen Browser.

## 0. Zuerst der TOT des Transceivers (2 min)

> **Sicherheit.** Der **TOT** (*Time Out Timer*) ist der Zeitgeber, der das Senden nach einer Höchstdauer abschaltet.
> Stellen Sie den des Transceivers **vor allem anderen** ein.

**Warum?** Aus der Ferne sehen Sie Ihren Transceiver nicht. Wenn der PC der Station hängt, das USB-Kabel abgeht oder
ein Programm während einer Sendung abstürzt, kann niemand mehr den Transceiver auf Empfang zurückschalten: Er würde
weiter einen Träger senden, die Frequenz stören, heiß werden, und Sie blieben dafür verantwortlich.

**Wozu er dient.** Die Station hat ihren eigenen TOT (standardmäßig 90 s) und einen Supervisor, der sie überwacht.
Der TOT des Transceivers ist die **letzte Barriere**: Er sitzt im Transceiver selbst und schaltet auch dann ab, wenn
der PC, das Kabel oder die Station ausgefallen sind.

**Wie.** Suchen Sie im Menü des Transceivers „Time-Out Timer“ („Time-Out Timer (CI-V)“ bei Icom) oder „TX TIME OUT
TIMER“ und wählen Sie **3 Minuten**: länger als der TOT der Station, schaltet er nie eine normale Sendung ab.

Den Menüpfad je nach Marke finden Sie in der Tabelle unten. Beim IC-7300MK2 liest die Station diese Einstellung bei
jeder Verbindung und warnt Sie, wenn sie auf OFF steht.

## Je nach Marke

Was sich von Gerät zu Gerät unterscheidet, in einer Zeile; die Einzelheiten stehen im Datenblatt des Transceivers,
wenn es eines gibt.

| | Icom | Yaesu | Kenwood | Xiegu |
|---|---|---|---|---|
| USB-Treiber (Windows) | „Icom USB Driver“, Version **1.80 oder neuer** | Silicon Labs **CP210x**; Port „Enhanced“ für die Steuerung | Treiber des Herstellers | Treiber des Herstellers |
| TOT des Transceivers | MENU > SET > Function > Time-Out Timer (CI-V) | OPERATION SETTING > GENERAL > TX TIME OUT TIMER | Handbuch des Transceivers | Handbuch des Transceivers |
| Stimme über USB | MENU > SET > Connectors > DATA MOD = **USB** (Senden in USB-D / LSB-D) | MOD SOURCE = **REAR** und REAR SELECT = **USB**, in jeder Betriebsart | Handbuch des Transceivers | Handbuch des Transceivers |
| Stand | **validiert** (IC-7300MK2) | **läuft** (FTDX10) | noch nicht getestet | noch nicht getestet |
| Datenblatt | [IC-7300MK2](postes/ic7300mk2.md) | [FTDX10](postes/ftdx10.md) | — | — |

Unter Linux (Debian, Raspberry Pi) ist kein Treiber zu installieren. Für einen noch nicht getesteten Transceiver:
Installieren Sie den USB-Treiber von der Website seines Herstellers und führen Sie die drei Tests aus Schritt 5
besonders sorgfältig durch.

## 1. Installieren (5 min)

Laden Sie das Paket der neuesten Version herunter: https://github.com/Bob56fr/openRemoteTRX/releases

<!-- onglets -->
#### Debian

Entpacken Sie `trx-remote-debian-X.Y.Z.zip`, öffnen Sie ein Terminal im entstandenen Ordner und dann

```
sudo bash install.sh
```

Melden Sie sich am Ende ab und wieder an.

#### Raspberry Pi

Karte mit Raspberry Pi Imager vorbereitet (Raspberry Pi OS 64 Bit, SSH aktiviert) und System aktuell: Teil 2, Reiter
Raspberry Pi. Dann das **gleiche Paket wie für Debian**: mit Desktop genau wie unter Debian; ohne Desktop von Ihrem
PC aus:

```
scp -o User=<konto> trx-remote-debian-X.Y.Z.zip <pi-adresse>:
ssh -t -l <konto> <pi-adresse>
```

und auf dem Pi: `unzip -q trx-remote-debian-X.Y.Z.zip && cd trx-remote-debian-X.Y.Z && sudo bash install.sh`.
Melden Sie sich am Ende neu an.

#### Windows

1. Installieren Sie zuerst **Hamlib 64 Bit** 4.7 oder neuer (`hamlib-w64-X.Y.Z.exe`):
   https://github.com/Hamlib/Hamlib/releases
2. Rechtsklick auf `trx-remote-windows-X.Y.Z.zip` > Eigenschaften > **Zulassen**, dann Alle extrahieren und Doppelklick
   auf **`installer.cmd`**.
3. Heimnetz im Profil **Privat**, **Energiesparmodus deaktiviert**.
<!-- /onglets -->

## 2. Konfigurieren (5 min)

Öffnen Sie **openRemoteTRX Console** (Debian: Anwendungsmenü oder `trx-console`; Raspberry Pi ohne Desktop:
`ssh -t -l <konto> <pi-adresse> trx-console`; Windows: Startmenü > **openRemoteTRX**), dann **Menü 2.1** (den
Assistenten). Der Transceiver wird nur gelesen: kein Senden. Worauf es ankommt:

| Frage | Antwort |
|---|---|
| Modell | geben Sie den Namen des Transceivers ein (z. B. `ic-7300`, `ftdx10`), wählen Sie aus der Liste |
| Port und Baudrate | der Port des Transceivers; die im CAT-Menü des Transceivers eingestellte Baudrate |
| PTT | **CAT**, wenn der Assistent es vorschlägt |
| Soundkarten | die des Transceivers, für Empfang und Senden |
| Erlaubte Bänder | die Bänder **Ihrer Lizenz**, sonst nichts. Leere Liste = nur Empfang |
| Maximale Dauer einer Sendung (TOT der Station) | **90** Sekunden (vorgeschlagen, höchstens 120) |
| Netzwerkzugang | „Lokales Netz oder VPN, über HTTPS“ (vorgeschlagen) |
| Konto | ein Benutzername; die Eingabetaste beim Passwort erzeugt ein starkes: **notieren Sie es** |

Für den Rest behält die Eingabetaste den vorgeschlagenen Wert.

## 3. Starten und prüfen (2 min)

1. **Menü 1.1**: Die Station startet, der Transceiver ist auf Empfang.
2. **Menü 6.1** (Diagnose): Beheben Sie jede Zeile mit **Fehler**, bevor Sie weitermachen; die Zeile sagt, was zu tun
   ist.

## 4. Verbinden (1 min)

1. Auf dem Telefon oder einem PC im Haus: `https://<stationsadresse>:8443` (Adresse oben in openRemoteTRX Console
   angezeigt).
2. Zertifikatswarnung: „Erweitert“, dann „Weiter“. Das ist normal (von Ihrer Station erstelltes Zertifikat); damit
   sie nicht mehr erscheint: Menü 4.4.
3. Melden Sie sich mit dem Konto aus dem Assistenten an. Kein Ton: Tippen Sie auf die Ton-Schaltfläche, der Browser
   hatte ihn blockiert.

Reservieren Sie die Adresse des PCs in Ihrem Router (DHCP-Reservierung): Wenn sie sich ändert, gilt das Zertifikat
nicht mehr.

## 5. Vor dem ersten Senden: drei Tests (3 min)

> **Sicherheit.** Dummy-Load angeschlossen, reduzierte Leistung, ein Band Ihrer Lizenz. Der **PTT ist ein Umschalter**:
> ein Druck zum Senden, ein Druck zurück auf Empfang. Schauen Sie nach jedem Test auf das **Display des
> Transceivers**, nicht nur auf die Seite.

| Test | Erwartet |
|---|---|
| Während einer Sendung Schaltfläche **STOP** | sofort Empfang |
| Während einer Sendung den Tab schließen (oder das WLAN des Telefons ausschalten) | Empfang nach etwa 2 s |
| Frequenz außerhalb Ihrer Bänder, dann PTT | Senden **abgelehnt**, Meldung auf der Seite |

Ein einziger Test misslungen: **Senden Sie nicht**, stoppen Sie die Station (Menü 1.2) und lesen Sie Teil 8. Die
vollständigen neun Tests stehen in Teil 3.5: Führen Sie sie durch, bevor Sie über eine Antenne senden.

## Und danach

- **Android-App**: Menü 4.1, QR-Code scannen (App im Test auf Einladung, Teil 0).
- **Von außen** (4G, anderes Netz): VPN oder Portfreigabe, Teil 5.
- **Alarme auf dem Telefon**: Menü 3.5, mit einem Testalarm.
- **Ein Problem**: Menü 6.1, dann der Bericht aus Menü 6.3 als Anhang zu einer Hilfeanfrage (Teil 8).
- **Alle Menüs der Konsole**: https://bob56fr.github.io/openRemoteTRX/console/de/
