# 8. Fehlersuche

## 8.1 Der erste Reflex

1. **Diagnose** (Menü 6.1): Sie sagt, was nicht stimmt und was zu tun ist.
2. **Protokoll** (Menü 6.2): Die Meldungen beginnen mit einem Code „ORT-NNNN“.
3. Jeder Code hat seine Erklärungsseite (Ursache, was zu tun ist): https://bob56fr.github.io/openRemoteTRX/erreurs/
   (Suchfeld: geben Sie den Code ein).

## 8.2 Häufige Probleme

| Symptom | Wahrscheinliche Ursache | Was zu tun ist |
|---|---|---|
| Die Diagnose findet den Transceiver nicht | Transceiver aus; falscher Port (der zweite Port des Transceivers, oder „Standard“ bei Yaesu); Baudrate des Transceivers anders als im Assistenten; Treiber fehlt (Windows) | einschalten; Menü 2.5 mit dem Steuerport wiederholen; die Baudrate einstellen (Datenblatt des Transceivers) |
| Kein Empfangston | Soundkarte des Transceivers vom Desktop belegt; Mikrofon für Apps gesperrt (Windows); Pegel zu niedrig (Einstellung des Transceivers, Audiopegel in Menü 2.9) | Teil 1.4; Teil 2, Reiter Windows; Datenblatt des Transceivers |
| Das Senden startet, aber nichts wird moduliert | der Transceiver nimmt in dieser Betriebsart die Stimme von seinem Mikrofon, nicht über USB (Icom: DATA MOD; Yaesu: MOD SOURCE und REAR SELECT) | Datenblatt des Transceivers, „Stimme über USB“ |
| Nur DATA-Betriebsarten können senden | der Assistent hat vermerkt, dass die Stimme nicht über USB geht | den Transceiver einstellen, dann den Assistenten neu starten und „ja“ antworten |
| ALC am Maximum, Ton übersteuert | USB-Eingangspegel des Transceivers zu hoch (Icom: USB MOD Level; Yaesu: RPORT GAIN) | Teil 3.4 |
| Der Transceiver geht beim Hochfahren des PCs auf Senden | eine RTS- oder DTR-Leitung des USB-Ports steuert das Senden (Icom: USB SEND / USB Keying; Yaesu: RPTT SELECT, PC KEYING) | **USB abziehen**, diese Einstellungen auf OFF stellen (Datenblatt des Transceivers) |
| Raspberry Pi langsam, Ton abgehackt, USB des Transceivers bricht ab | Netzteil zu schwach oder Überhitzung (`vcgencmd get_throttled` anders als `throttled=0x0`) | offizielles Netzteil, Lüfter (Teil 2, Reiter Raspberry Pi) |
| „Mikrofon nicht verfügbar“ auf der Seite | Seite über HTTP geöffnet | die Adresse mit **https://** öffnen |
| Seite vom Telefon aus nicht erreichbar | Station gestoppt; Adresse geändert; Netzwerk im Profil Öffentlich (Windows) | Menü 1.1; Teil 4.1; Teil 2, Reiter Windows |
| Verbunden, aber kein Ton aus der Ferne | UDP geht nicht durch (Portfreigabe am Router) | VPN (Teil 5) |
| Abbrüche alle 15 bis 30 s | zwei Geräte mit demselben VPN-Profil | ein Profil pro Gerät |
| Senden von selbst abgeschaltet | Höchstdauer erreicht, Telefon antwortet nicht mehr, Frequenz außerhalb der Bänder, Operator vor Ort | normal: der Grund wird auf der Seite und im Protokoll angezeigt |
| Nichts antwortet mehr, Alarm „Station in Sicherheitsabschaltung“ | wiederholte Ausfälle | Teil 6.2 |
| Transceiver-Test abgelehnt: „ORT-9313 … die Station läuft“ | der Test braucht den Transceiver für sich allein | die Station stoppen (Menü 1.2), den Test wiederholen, die Station neu starten |
| Ein Werkzeug bricht ab mit „ORT-9312 … unerwarteter Fehler“ | Softwarefehler in einem unvorhergesehenen Fall (neuer Transceiver, Soundkarte…) | die Meldung nennt die Detaildatei (Ordner `plantages`): sie der Hilfeanfrage beifügen (Teil 8.3) |

## 8.3 Hilfe anfordern

1. Menü **6.3**: erstellt einen Fehlerbericht (Zip auf dem Schreibtisch, oder im Ordner des Kontos auf einem Pi ohne
   Desktop) **ohne jedes Passwort** (unter Windows wie unter Debian). In der Webkonsole holt ihn die Schaltfläche
   **„Bericht herunterladen“** direkt auf Ihren PC oder Ihr Telefon. Die Spuren der bei einem Fehler abgebrochenen
   Werkzeuge (Code ORT-9312) liegen im Ordner `plantages` des Zustandsordners der Station, und der Bericht fügt sie
   bei. Um ihn selbst zu lesen: Menü **6.6**, das den Link zum **Analysewerkzeug** gibt; Sie legen das Zip dort ab und
   die Analyse geschieht in Ihrem Browser (der Bericht wird nirgendwohin gesendet).
2. Von der Webseite aus: Abschnitt „Problem melden“ (Text vor dem Senden geprüft).
3. Öffnen Sie ein Ticket auf https://github.com/Bob56fr/openRemoteTRX/issues mit dem Formular **auf Deutsch**
   („Fehler melden“), beschreiben Sie, was Sie taten, was Sie erwarteten, was geschehen ist, und fügen Sie den Bericht
   bei.
4. **Aus der Ferne Hilfe erhalten** (Monitoring zwischen Stationen, Menü **6.5**, zuerst zu aktivieren: Teil 9): Die
   Person, die Ihnen hilft, erstellt einen Code aus 10 Zeichen und diktiert ihn Ihnen; geben Sie ihn bei Auswahl 4 ein
   und vergleichen Sie dann mündlich die auf beiden Seiten angezeigten **6 Ziffern**. Verschieden: Antworten Sie
   „nein“, die Verbindung wird gelöscht. Wählen Sie dann, was Sie senden („Diagnose“ empfohlen; Frequenz und
   Betriebsart nur, wenn Sie wollen). Die Person sieht dann den Zustand Ihrer Station und ihre Fehlercodes,
   **maskiert** (weder Passwort noch Adresse noch Seriennummer), und kann Sie um den Unterstützungsmodus **bitten**
   (Neuigkeiten alle 30 Sekunden, für eine begrenzte Dauer): Sie selbst nehmen an (Auswahl 7). Sie kann auf Ihrer
   Station **nichts steuern**. Sie beenden alles, wann Sie wollen (Auswahl 9). Sie kann Sie auch um Ihren
   **Fehlerbericht** bitten (den aus Punkt 1, vollständig maskiert); Sie können ihn auch selbst senden (Auswahl 10).
   Auf ihrer Seite erhält sie einen Alarm auf ihrem Telefon, wenn Ihre Station keine Neuigkeiten mehr gibt. **Fern von
   Ihrer Station** geht alles auch auf der Webseite, Rubrik „Monitoring“: Schaltfläche „Hilfe erhalten: ich habe einen
   Code“, Vergleich der 6 Ziffern, Wahl dessen, was gesendet wird, Antwort auf Anfragen, Ende.
