# Eine openRemoteTRX-Station in Betrieb nehmen: Handbuch für den Operator

Dieses Handbuch begleitet Sie der Reihe nach vom Auspacken bis zur ersten Verbindung von außen. Es gilt für jeden
Transceiver, den Hamlib kennt; was zu einem bestimmten Modell gehört (USB-Treiber, Menüs, Ports), steht in seinem
**Transceiver-Datenblatt**:

- [Icom IC-7300MK2](postes/ic7300mk2.md): an einem echten Gerät **validiert**;
- [Yaesu FTDX10](postes/ftdx10.md): vorbereitet, **Validierung läuft**.

Für einen anderen Transceiver: sein Handbuch, die Tabelle „Je nach Marke“ im [Schnellstart](demarrage-rapide.md)
und die Tests aus Teil 3, die als Validierung dienen: Führen Sie alle durch, an einer Dummy-Load, und melden Sie das
Ergebnis (Teil 8, „Hilfe anfordern“). Stand jedes getesteten Transceivers: https://bob56fr.github.io/openRemoteTRX/postes/

> **Eilig?** Der [Schnellstart](demarrage-rapide.md) führt in einer Viertelstunde vom angeschlossenen Transceiver
> zur Webseite, einschließlich TOT des Transceivers. Kehren Sie beim ersten Problem zu den Teilen unten zurück.

## Der Ablauf

| Teil | Was Sie tun | Ungefähre Dauer |
|---|---|---|
| [Schnellstart](demarrage-rapide.md) | das Wichtigste für Ungeduldige, einschließlich Sicherheitstests | 15 min |
| [0. Bevor Sie beginnen](00-avant-de-commencer.md) | Hardware, Vorschriften, Wahl zwischen Debian, Raspberry Pi oder Windows | 15 min Lesezeit |
| [1. Den Transceiver vorbereiten](01-preparer-le-poste.md) | Verkabelung, USB-Treiber, Menüs des Transceivers | 30 min |
| [2. Die Station installieren](02-installer-la-station.md) | Software auf dem PC oder dem Raspberry Pi | 20 min (Pi: 1 h mit der SD-Karte) |
| [3. Den TRX einbinden und testen](03-integrer-et-essayer-le-trx.md) | Assistent, Tests im Empfang und dann beim Senden, Sicherheitstests | 1 h 30 |
| [4. Im LAN verwenden](04-utilisation-sur-le-lan.md) | Webseite, Telefon, Android-App | 30 min |
| [5. Aus der Ferne verwenden](05-utilisation-a-distance.md) | VPN oder Portfreigabe, Test über 4G | 1 h |
| [6. Station ohne Aufsicht](06-station-sans-surveillance.md) | Alarme, Neustart nach Stromausfall, Schutzmaßnahmen | 30 min |
| [7. Täglicher Betrieb](07-exploitation-au-quotidien.md) | starten, überwachen, aktualisieren, sichern | zum Lesen |
| [8. Fehlersuche](08-depannage.md) | Fehlercodes, häufige Probleme, Hilfe anfordern | bei Bedarf |
| [9. Optionale Funktionen](09-fonctions-facultatives.md) | Besucher, DX-Cluster, FreeDV, SELCALL, SWR… | nach Wahl |
| [Glossar](glossaire.md) | die Begriffe des Projekts: wer ist was | bei Bedarf |
| [10. Checkliste zum Abhaken](10-recapitulatif.md) | wissen, wo Sie stehen | |

Transceiver-Datenblätter: [Icom IC-7300MK2](postes/ic7300mk2.md), [Yaesu FTDX10](postes/ftdx10.md). Schema der
Bausteine der Station: Teil 0, „So ist es aufgebaut“.

## Wie Sie dieses Handbuch lesen

- Die **Menüs von openRemoteTRX Console** werden mit ihrer Nummer angegeben: „Menü 2.1“ = Thema 2 (Transceiver und
  Hardware), Menü 1. Unter Windows öffnet die Verknüpfung Startmenü > **openRemoteTRX** dieselbe Konsole (Teil 2).
  Die Konsole öffnet sich im **Vollbild**: links die Themen mit ihrem Symbol (Pfeiltasten und Eingabetaste), rechts
  die Hilfe zum gewählten Menü; Sie können die Nummer auch in der Textkonsole eingeben (`trx-console --texte`).
- Ein Kasten **„Sicherheit“** kennzeichnet einen Punkt, der das Senden betrifft: Überspringen Sie ihn nicht.
- Was sich je nach System unterscheidet, steht in **Reitern** Debian / Raspberry Pi / Windows: Wählen Sie Ihren
  einmal, die Wahl gilt für die ganze Seite. Auf GitHub stehen die Reiter untereinander.
- Dieses Handbuch gibt es auch als Webseite, mit einer Checkliste zum Abhaken online, und als **PDF** zum Drucken
  (Link „Als PDF herunterladen“ oben auf der Seite): https://bob56fr.github.io/openRemoteTRX/guide/de/
