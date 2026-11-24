# Glossar

Die Begriffe des Handbuchs, nach Themen geordnet. Das Schema der Bausteine steht in
[Teil 0](00-avant-de-commencer.md#so-ist-es-aufgebaut).

## Die Hardware

| Begriff | Was es ist |
|---|---|
| **Transceiver**, **TRX** | Ihr Funk-Sendeempfänger (Funkgerät) |
| **Stations-PC** | der Rechner neben dem Transceiver, dauerhaft eingeschaltet, auf dem die Station läuft: ein PC mit Debian oder Windows, oder ein Raspberry Pi |
| **Raspberry Pi** | kleiner Rechner auf einer Platine, sparsam; der Pi 4 (4 GB) oder der Pi 5 mit Raspberry Pi OS 64 Bit kann als Stations-PC dienen |
| **Hardware-Watchdog** | ein Chip des Raspberry Pi, der ihn neu startet, wenn das System länger als 15 s hängt; von der Installation eingeschaltet |
| **Station** | das Ganze aus Transceiver + PC + openRemoteTRX-Software; „die Station starten“ = ihre Dienste starten |
| **CAT** | *Computer Aided Transceiver*: die Steuerung des Transceivers durch den Rechner (Frequenz, Betriebsart, Senden…) |
| **Enhanced COM Port** / **Standard COM Port** | die beiden seriellen Ports, die manche Yaesu (FTDX10…) über ihr USB-Kabel auf dem PC anlegen: der erste dient der CAT, der zweite (RTS/DTR-Leitungen) wird von der Station nicht benutzt |
| **Soundkarte des Transceivers** | die im Transceiver eingebaute Soundkarte, vom PC über das USB-Kabel gesehen („USB Audio CODEC“ bei Yaesu, „USB Audio Device“ beim IC-7300MK2): Empfangston zum PC, Stimme zum Transceiver |
| **Dummy-Load** | 50-Ω-Widerstand, der die Antenne ersetzt: Der Transceiver sendet, ohne abzustrahlen. Pflicht für alle Tests |
| **ALC** | Anzeige des Transceivers, die zeigt, ob die Modulation zu stark ist; dient zum Einstellen des Sprachpegels |
| **SWR** | Stehwellenverhältnis: Anpassung der Antenne. Die Station kann es über ein Band messen |
| **VFO A / VFO B** | die beiden Arbeitsfrequenzen des Transceivers; die Seite zeigt, welche aktiv ist |
| **Split** | Empfang auf einer Frequenz, Senden auf einer anderen |

## Die Software der Station

| Begriff | Was es ist |
|---|---|
| **openRemoteTRX** | der Name des Projekts; die Android-App trägt diesen Namen, die Station heißt ebenfalls „openRemoteTRX“ |
| **Hamlib** | die freie Bibliothek, die mit rund 300 Transceiver-Modellen sprechen kann; jedes Modell hat eine **Nummer** (IC-7300MK2 = 3094, FTDX10 = 1042) |
| **rigctld** | das Programm von Hamlib, das die Verbindung zum Transceiver hält; es hört nur auf dem PC selbst, nie im Netzwerk |
| **Gateway** (`trx-gateway`) | das Herz der Station: liefert die Webseite aus, prüft die Konten, überträgt den Ton und **entscheidet über das Senden** |
| **Supervisor** (`trx-supervisor`) | der unabhängige Wächter: überwacht das Gateway, rigctld und den PC; er kann **nur abschalten** (eine Sendung), einen Dienst neu starten oder die Station in die Sicherheitsabschaltung versetzen; sendet die Alarme |
| **openRemoteTRX Console** (`trx-console`) | die Steuerzentrale der Station in einem Terminal: installieren, konfigurieren, starten, testen, aktualisieren, Fehler suchen (nummerierte Menüs „2.1“, „2.2“…) |
| **Konfigurationsassistent** (`trx-setup`) | die Fragen, die die Konfiguration erstellen (Menü 2.1); er fragt den Transceiver nur lesend ab |
| **Dashboard**, **Übersicht** (`trx-monitor`) | der Live-Zustand in einem Terminal (Menü 1.3); eine einzige Aktion: STOP TX |
| **Vitalwerte-Dashboard** | Seite nur zum Lesen (Port 8450, Debian und Raspberry Pi) für einen kleinen Bildschirm neben dem Transceiver oder ein Telefon |
| **Anzeige** | die Statusanzeige der Station in der oberen Leiste (Debian) oder neben der Uhr (Windows); nur lesen |
| **Geführter Test** (`trx-hwtest`) | der schrittweise Test des echten Transceivers (Menü 2.2) |
| **Qualifizierung** (`trx-qualif`) | die vollständige Erkundung dessen, was Hamlib für einen Transceiver angibt (Menü 8.3), für Experten |
| **`station.toml`** | die Konfigurationsdatei der Station: Transceiver, Ports, Konten, erlaubte Bänder, Sicherheiten |
| **Transceiver-Profil** | eine unter einem Namen gespeicherte Transceiver-Konfiguration, um den Transceiver zu wechseln (Menü 2.3) |
| **Modul** | eine optionale Funktion, die neben dem Gateway läuft (DX-Cluster, Gruppen-Anwesenheit…) |
| **Signierte Aktualisierung** | die Debian-Pakete sind signiert: Die Aktualisierung über das Internet (Menü 7.1) lehnt ein Paket ab, dessen Signatur nicht passt; ein nicht signiertes Zip (Menü 7.3) verlangt eine Bestätigung |

## Auf Benutzerseite

| Begriff | Was es ist |
|---|---|
| **Webseite** | die Oberfläche der Station in einem Browser, unter der Adresse `https://<stationsadresse>:8443` |
| **Android-App** | die App openRemoteTRX: dasselbe wie die Seite, dazu Senden bei ausgeschaltetem Bildschirm, Headset, Auto |
| **Android Auto** | die Anzeige der App auf dem Bildschirm des Autos: Hören, Speicher, PTT, ohne Grafik |
| **Fahrmodus** | der reduzierte Bildschirm der App im Auto: kein Touch-PTT |
| **Operator-Konto** | Benutzername + Passwort, die erlauben, den Transceiver zu steuern und zu senden; **eines pro Gerät** (`PC`, `S25`…), verwaltet in Menü 4.3 |
| **Besucher** | Konto nur für Empfang: hört zu und sieht den Bildschirm, keinerlei Befehl |
| **Kopplung** | das Hinzufügen der Station in der App, über den **QR-Code** aus Menü 4.1 |

## Die Sendesicherheit

| Begriff | Was es ist |
|---|---|
| **PTT** | *Push To Talk*: das Umschalten auf Senden |
| **PTT als Umschalter** | ein Druck zum Senden, ein Druck zurück auf Empfang (nie „solange man drückt“) |
| **STOP** | sofort zurück auf Empfang, immer verfügbar |
| **TOT** | *Time Out Timer*: Höchstdauer einer Sendung (standardmäßig 90 s, höchstens 120 s), mit einem Piepton 10 s vor dem Abschalten |
| **Absoluter TOT** | Dauer, nach der der Supervisor jede Sendung abschaltet, selbst eine mit dem Mikrofon des Transceivers (135 s; 5 Minuten, wenn der Operator den Transceiver kurz vorher oder währenddessen berührt hat) |
| **Heartbeat** | das Lebenszeichen, das das Telefon während des Sendens zweimal pro Sekunde schickt; fehlt es 2 s, zurück auf Empfang |
| **Erlaubte Bänder** | die Frequenzbereiche, in denen die Station zu senden bereit ist; leere Liste = nur Empfang |
| **Operator vor Ort**, **Bediener vor Ort** | jemand, der den Transceiver direkt bedient: Das Senden aus der Ferne ist während seiner Sendung und dann 2 Minuten lang gesperrt |
| **Sende-Audiotor** | der Durchgang des Tons zum Transceiver, vom Gateway nur während einer erlaubten Sendung geöffnet |
| **Sicherheitsabschaltung** | der Zustand, in den der Supervisor die Station nach wiederholten Ausfällen versetzt: gefahrlos angehalten (Empfang, Zugang gesperrt), wartet sie auf einen Eingriff; Sie nehmen sie über Menü 1.4 wieder in Betrieb („Station wieder in Betrieb nehmen“) |
| **Sendezeitbegrenzung des Transceivers** (TX TIME OUT TIMER) | die eigene Abschaltung des Transceivers, unabhängig von der Station: die letzte Barriere |

## Das Netzwerk

| Begriff | Was es ist |
|---|---|
| **LAN**, **Lokales Netzwerk** | das Netzwerk zu Hause, hinter dem Router |
| **Port 8443** | der Port, an dem das Gateway Seite und App empfängt |
| **HTTPS**, **Zertifikat** | die Verschlüsselung der Verbindung; die Station erstellt ihr eigenes Zertifikat („selbstsigniert“): Der Browser warnt beim ersten Mal |
| **Fingerabdruck des Zertifikats** | die Kurzfassung des Zertifikats, die sich die App merkt, um eine falsche Station abzulehnen |
| **WebRTC** | die Technik, die den Ton in Echtzeit überträgt, über **UDP** |
| **VPN** | ein verschlüsselter Tunnel, der das Telefon von überall „in“ das Netzwerk zu Hause holt (WireGuard, Tailscale…) |
| **VPN-Profil** | die Schlüssel eines Geräts im VPN: ein Profil pro Gerät, nie geteilt |
| **Portfreigabe**, **Offener Port** | der Router, der Verbindungen aus dem Internet zur Station durchlässt; verlangt ein echtes Zertifikat und ein starkes Passwort |
| **SSH** | die verschlüsselte Verbindung, die von Ihrem PC aus ein Terminal eines anderen Rechners öffnet: `ssh -l <konto> <adresse>`; dient dazu, einen Raspberry Pi ohne Bildschirm zu steuern |
| **CGNAT** | vom Provider zwischen mehreren Kunden geteilte Adresse: Kein Port kann geöffnet werden, ein VPN ist nötig |
| **ntfy** | der Benachrichtigungsdienst, der die Alarme der Station auf Ihr Telefon bringt |
| **ORT-Code** | die Nummer einer Meldung der Station („ORT-5031“); jeder Code hat seine Erklärungsseite |
