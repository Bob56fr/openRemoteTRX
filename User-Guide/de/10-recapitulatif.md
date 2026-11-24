# 10. Checkliste: Wo stehen Sie?

Haken Sie nach und nach ab. Auf der Webseite des Handbuchs werden die Kästchen online abgehakt und bleiben in Ihrem
Browser gespeichert; auf GitHub drucken Sie diese Seite oder schreiben die Liste ab.

## 0. Bevor Sie beginnen

- [ ] Bedingungen für den Fernbetrieb für meine Lizenz geprüft
- [ ] Dummy-Load für die Tests vorhanden
- [ ] System gewählt (Debian empfohlen, Raspberry Pi oder Windows) und Paket heruntergeladen

## 1. Den Transceiver vorbereiten

- [ ] USB-Treiber des Herstellers vor dem Anschließen des Kabels installiert (Windows)
- [ ] Steuerport des Transceivers ermittelt (Datenblatt des Transceivers)
- [ ] CAT-Baudrate des Transceivers notiert, Menüs aus dem Datenblatt eingestellt
- [ ] Stimme über USB in jeder verwendeten Betriebsart eingestellt
- [ ] Keine RTS- / DTR-Leitung des USB-Ports steuert das Senden
- [ ] VOX aus, Sendezeitbegrenzung des Transceivers auf 3 min, Höchstleistung eingestellt
- [ ] Soundkarte des Transceivers nicht mehr Standard-Audiogerät des PCs

## 2. Die Station installieren

- [ ] Software installiert (install.sh oder installer.cmd)
- [ ] Sitzung neu geöffnet (Debian, Raspberry Pi); Netzwerkprofil Privat und Energiesparmodus deaktiviert (Windows)
- [ ] Raspberry Pi: offizielles Netzteil, Lüfter, `throttled=0x0`

## 3. Den TRX einbinden und testen

- [ ] Assistent abgeschlossen (Modell meines Transceivers, Steuerport, PTT über CAT, Bänder meiner Lizenz)
- [ ] Diagnose ohne Fehler
- [ ] Geführter Test nur im Empfang erfolgreich
- [ ] Geführter Test mit Senden an der Dummy-Load erfolgreich
- [ ] Station gestartet, Seite geöffnet, Modulation mit der ALC eingestellt (USB-Eingangspegel des Transceivers)
- [ ] Test 1: STOP beendet das Senden
- [ ] Test 2: Abschaltung nach 90 s, Warnung 10 s vorher
- [ ] Test 3: Verbindung während des Sendens getrennt, zurück auf Empfang
- [ ] Test 4: Bildschirm während des Sendens gesperrt, zurück auf Empfang
- [ ] Test 5: Senden außerhalb meiner Bänder abgelehnt
- [ ] Test 6: Senden mit dem Mikrofon des Transceivers, Fern-PTT gesperrt
- [ ] Test 7: STOP TX im Dashboard
- [ ] Test 8: Stopp der Station während des Sendens
- [ ] Test 9: kein Wechsel auf Senden beim Hochfahren des PCs (oder des Pi)
- [ ] Ergebnis der Tests gemeldet, falls mein Transceiver noch nicht validiert ist (Ticket „<mein Transceiver>: Tests zur Inbetriebnahme“)

## 4. Im LAN verwenden

- [ ] IP-Adresse für den Stations-PC im Router reserviert
- [ ] Webseite über https geöffnet, Zertifikat akzeptiert, Mikrofon erlaubt
- [ ] Ein Konto pro Gerät (Menü 4.3), lange Passwörter
- [ ] Android-App per QR-Code gekoppelt (Menü 4.1), Sendetest und STOP

## 5. Aus der Ferne verwenden

- [ ] Wahl getroffen: VPN (empfohlen) oder Portfreigabe
- [ ] Ein VPN-Profil pro Gerät
- [ ] Über 4G: Seite, Empfangston, Senden an der Dummy-Load, STOP
- [ ] Über 4G: Flugmodus während des Sendens, zurück auf Empfang

## 6. Station ohne Aufsicht

- [ ] ntfy-Alarme empfangen (langes und geheimes Thema), Meldung „Station in Betrieb“ gesehen
- [ ] PC so eingestellt, dass er nach einem Stromausfall wieder startet (ein Pi tut das von selbst)
- [ ] USV, Blitzschutz, Belüftung des Transceivers
- [ ] Ich kann die Station nach einer Sicherheitsabschaltung wieder in Betrieb nehmen (Menü 1.4), nachdem ich die Ursache gefunden habe

## 7. Täglicher Betrieb

- [ ] Ich kann die Station starten, stoppen und überwachen
- [ ] Ich kann aktualisieren und zur vorherigen Version zurückkehren
- [ ] Konfiguration und Zertifikat an anderem Ort gesichert
- [ ] Profil des Transceivers gespeichert (Menü 2.3)

## Station in Betrieb

- [ ] Erstes Senden über die Antenne, in meinen Bändern, mit Identifikation
