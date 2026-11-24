# 3. Den TRX einbinden und testen

> **Sicherheit.** Während dieses ganzen Teils: **Dummy-Load** an der Antennenbuchse, **reduzierte Leistung**
> (zum Beispiel 10 W), niemand in der Nähe der abgeklemmten Antenne.

## 3.1 Der Konfigurationsassistent (Menü 2.1)

Der Transceiver wird nur **lesend** abgefragt: kein Senden während des Assistenten. Nichts wird gespeichert, wenn Sie
mittendrin abbrechen. Die Werte für Ihren Transceiver stehen in seinem Datenblatt:

| Frage | Antwort |
|---|---|
| Modell des Transceivers | geben Sie seinen Namen ein (`ic-7300`, `ftdx10`…) und wählen Sie aus der Liste (Hamlib-Nummer im Datenblatt: IC-7300MK2 = 3094, FTDX10 = 1042). Bei manchen Geräten erinnert der Assistent an die zu prüfenden Menüs (Teil 1) |
| Serieller Port für CAT | der **Steuer**port (Debian und Raspberry Pi: automatisch vorgeschlagen; Windows: der in Teil 1 notierte COM) |
| Baudrate | **gleich** der im Transceiver eingestellten CAT-Baudrate |
| PTT-Methode | **CAT** (vorgeschlagen) |
| Geht die Stimme über USB? | **ja**, wenn der Transceiver in Telefonie über USB moduliert (Teil 1); sonst ist das Senden auf Datenbetriebsarten beschränkt |
| Soundkarten (Empfang, Senden) | die des **Transceivers** für beide (ihr Name steht im Datenblatt) |
| KW-Spektrum über einen zweiten Port | der **zweite Port** des Transceivers, wenn er einen hat (Icom IC-7300MK2…); sonst **keiner** |
| Zum Senden erlaubte Bänder | nur die Bänder **Ihrer Lizenz**. Leere Liste = nur Empfang |
| Netzwerkzugang | „**Lokales Netz oder VPN, über HTTPS mit einem hier erzeugten Zertifikat**“ (empfohlen) |
| Konten | ein Benutzername (Buchstaben, Ziffern, `_`, `-`) und ein **langes Passwort** (Eingabetaste = ein starkes Passwort wird erzeugt: notieren Sie es); Eingabetaste bei leerem Benutzernamen zum Beenden |
| Höchstleistung des Transceivers | die Ihres Transceivers (oft **100** Watt) |
| Maximale Dauer einer Sendung (TOT) | **90** Sekunden (Standardwert, Obergrenze 120) |
| Wiedergabe von Aufnahmen | **nein** (Standardantwort) |

Am Ende zeigt der Assistent die zu öffnende Adresse (`https://<stationsadresse>:8443`) und den **Fingerabdruck des
Zertifikats** an (nützlich für die Android-App, Teil 4).

## 3.2 Die Diagnose (Menü 6.1)

Sie prüft alles, ohne etwas zu ändern: Jede Zeile ist **OK**, zu **beobachten** oder **Fehler**, mit dem Vorgehen.
Beheben Sie jeden Fehler, bevor Sie weitermachen (Menü 8.1 für eine Einstellung, oder starten Sie den Assistenten neu).

Häufige Fehler in diesem Stadium: falscher Port (der zweite Port des Transceivers statt des Steuerports; Yaesu:
Standard statt Enhanced), Baudrate des Transceivers anders als im Assistenten, Soundkarte des Transceivers vom
Desktop belegt (Teil 1.4); bei einem Raspberry Pi ein zu schwaches Netzteil („Unterspannung“, Teil 2).

## 3.3 Der geführte Test des Transceivers (Menü 2.2)

Die Station ist während des Tests gestoppt.

1. **Auswahl 1, nur Empfang**: CAT-Verbindung, Empfangston, Wechsel von Frequenz und Betriebsart, Filterbreiten.
   Hören Sie, ob der Empfangston sauber und in einem richtigen Pegel ist (sonst: im Datenblatt angegebene Einstellung
   des Transceivers, dann Empfangs-Audiopegel in Menü 2.9).
2. **Auswahl 2, Empfang, dann Senden**: Dummy-Load, reduzierte Leistung. Jeder Wechsel auf Senden verlangt die
   Eingabe von `SENDEN`.

Kopieren Sie die am Bildschirm angezeigte **Zusammenfassung am Ende**: Sie dient dem Validierungsbericht.

## 3.4 Die Station starten und die Modulation einstellen

1. Menü **1.1**: Die Station startet (der Transceiver wird beim Start immer auf Empfang gesetzt). Machen Sie einige
   Sekunden später erneut eine Diagnose (Menü 6.1).
2. Öffnen Sie die Seite `https://<stationsadresse>:8443` von einem Telefon oder einem PC im Netzwerk (Einzelheiten
   und Zertifikatswarnung: Teil 4), melden Sie sich an.
3. Erlaubtes Band, Dummy-Load, eine Telefonie-Betriebsart, die Ihr Transceiver über USB moduliert (USB oder LSB; bei
   einem Icom USB-D oder LSB-D, Teil 1): Drücken Sie den **PTT** (Umschalter: ein Druck zum Senden, ein Druck zurück
   auf Empfang), sprechen Sie einige Sekunden normal, drücken Sie erneut.
4. Beobachten Sie die **ALC** auf der Seite: Sie soll bei Sprachspitzen ausschlagen, ohne am Maximum zu bleiben.
   Passen Sie den USB-Eingangspegel des Transceivers an, bis Sie dieses Ergebnis erhalten (Icom: **USB MOD Level**;
   Yaesu: **RPORT GAIN** im Menü der verwendeten Betriebsart; der genaue Name steht im Datenblatt des Transceivers).

## 3.5 Die Sicherheitstests

Führen Sie **alle** durch, an einer Dummy-Load, vor jedem Senden über eine Antenne. Jeder muss damit enden, dass der
Transceiver auf Empfang zurückgeht (prüfen Sie es am Display des Transceivers, nicht nur auf der Seite).

| # | Test | Erwartetes Ergebnis |
|---|---|---|
| 1 | Während einer Sendung Schaltfläche **STOP** der Seite | sofort zurück auf Empfang |
| 2 | Senden, ohne etwas anzufassen | Countdown und Piepton 10 s vor dem Ende, zurück auf Empfang nach **90 s** |
| 3 | Während einer Sendung das WLAN des Telefons ausschalten (oder den Tab schließen) | zurück auf Empfang nach etwa **2 s** |
| 4 | Während einer Sendung vom Telefon aus den Bildschirm sperren | zurück auf Empfang |
| 5 | Eine Frequenz außerhalb Ihrer erlaubten Bänder einstellen, PTT drücken | Senden **abgelehnt**, Meldung auf der Seite |
| 6 | **Mit dem Mikrofon des Transceivers** senden (ohne die Station) | die Seite zeigt den Operator vor Ort an und sperrt den Fern-PTT während der Sendung und dann 2 Minuten |
| 7 | Während einer Sendung Taste **STOP TX** im Dashboard (Menü 1.3) | zurück auf Empfang |
| 8 | Während einer Sendung die Station stoppen (Menü 1.2) | zurück auf Empfang |
| 9 | Den PC (oder den Pi) neu starten, Transceiver eingeschaltet | der Transceiver geht während des Starts **nie** auf Senden |

Ein Test, der nicht das erwartete Ergebnis liefert: **Verwenden Sie die Station nicht zum Senden**, stoppen Sie sie
(Menü 1.2) und bitten Sie um Hilfe (Teil 8) mit dem Bericht aus Menü 6.3.

## 3.6 Weitergehend (optional)

- **Qualifizierung des Transceivers** (Menü 8.3, `trx-qualif`): für einen Experten, der alles prüfen will, was Hamlib
  für Ihren Transceiver angibt. Beginnen Sie mit Auswahl 2 (Erkundung ohne Senden); der erzeugte Bericht ist wertvoll,
  um das Datenblatt des Transceivers zu validieren. Auswahl 6 („Qualifizierungskoffer“) führt alles nacheinander aus,
  für ein Teammitglied, das zum Qualifizieren des Transceivers gekommen ist: Aufnahme des Transceivers vorher und
  nachher (was von Hand zurückzustellen ist), Erkundung, Qualifizierung, die zeitgemessenen Sicherheitstests aus § 3.5
  und ein Zip-Bericht für die Entwickler.
- **Transceiver-Profil** (Menü 2.3): speichert die Konfiguration unter einem Namen („IC-7300 Zuhause“), um sie später
  wieder zu laden, wenn Sie den Transceiver wechseln.

## 3.7 Die Validierung melden

Ist Ihr Transceiver noch nicht validiert (Liste: https://bob56fr.github.io/openRemoteTRX/postes/), zählt Ihr
Ergebnis: Öffnen Sie ein Ticket „Fehler melden“ (auch wenn alles gut geht, Titel „<Ihr Transceiver>: Tests zur
Inbetriebnahme“) mit der Zusammenfassung des geführten Tests, dem Ergebnis der 9 Sicherheitstests und, falls er ein
Datenblatt hat, den Punkten, die es zu prüfen verlangt.
