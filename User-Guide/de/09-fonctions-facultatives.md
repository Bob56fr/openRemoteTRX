# 9. Optionale Funktionen

Alle sind anfangs **deaktiviert**. Aktivieren Sie sie, sobald die Station validiert ist (Teile 3 bis 5): Menü **5.5**
„Funktionen in Betrieb“ schaltet sie mit einer Nummer ein oder aus (es startet auch das Modul der Funktion); eine
Funktion, die weitere Einstellungen braucht, wird abgelehnt, mit dem Menü, in dem diese vorzunehmen sind.

| Funktion | Wozu sie dient | Wo sie aktiviert wird |
|---|---|---|
| **Besucher** nur im Empfang | Konten, die der Station zuhören und den Bildschirm sehen, ohne **irgendeinen** Befehl (Funkclub, Vorführung) | Menü 4.2, dann der Schalter „Mithören der Besucher“ der Seite |
| **DX-Cluster** | Spots auf dem Spektrum und Markierungen auf den Band-Schaltflächen | Menü 5.1 |
| **FreeDV** RADE V1 (Empfang) | digitale FreeDV-Sprache, von der Station dekodiert | Decoder kompilieren (`sudo bash compiler-freedv.sh` im Ordner des Debian-Pakets), dann Menü 5.5 („FreeDV-Empfang“); der Locator der FreeDV-Aktivität: `[freedv] locator` (Menü 8.1) |
| **SELCALL** | Squelch per Gruppenruf in SSB | Menü 5.5, dann die Rubrik SELCALL der Seite |
| **SWR-Messung** | SWR-Kurve der Antenne über ein Band, in FM, reduzierte Leistung | Webseite oder App; die Station sendet: nur erlaubte Bänder |
| **Gruppen-Anwesenheit** | sehen, welche Freunde mit openRemoteTRX im QSO sind, und zu ihnen wechseln | Menü 5.3 |
| **Monitoring zwischen Stationen** | aus der Ferne von einer Vertrauensperson Hilfe erhalten oder einem anderen Operator helfen: Zustand der Station und Fehlercodes, maskiert und verschlüsselt, ohne VPN und ohne Portfreigabe; kein Befehl an die unterstützte Station möglich | Menü 5.5 („Monitoring zwischen Stationen“), dann Menü 6.5 oder Rubrik „Monitoring“ der Seite (Teil 8.3) |
| **Breizh Audio Box** | Verarbeitung der Stimme auf einem anderen PC im LAN | Menü 5.2 |
| **Live-Übertragung** | den Ton des Transceivers einigen **Hörern** im Internet hörbar machen, ohne Konto auf der Station: Sie hören auf der Seite eines Übertragungsservers (privater Kanal mit Benutzername und Passwort, oder öffentlich); Anzeige **ÜBERTRAGUNG** auf der Seite immer sichtbar; Ihre Stimme während Ihrer Sendungen wird nur übertragen, wenn Sie es verlangen; außerhalb Ihrer Bänder Stille für die Hörer (außer anderer Einstellung): ihre Seite nennt den Grund (außerhalb der Bänder, Senden ohne Ihre Stimme, kein Ton mehr vom Transceiver), wie Menü 5.6 und die Anzeige 🔇; Alarm auf dem Telefon zu Beginn und am Ende | Menü 5.6 (Server und Geheimnisse vom Administrator des Servers), Menü 5.5 („Live-Übertragung“), dann Menü 5.6 oder Rubrik „Live-Übertragung“ der Seite zum Starten und Beenden |
| **Wiedergabe** einer Aufnahme | eine Aufnahme des Empfangs erneut aussenden | im Assistenten gewährt; im Amateurfunkdienst in der Regel **verboten** |
| **SDR-Empfänger** (SDRplay) | zweiter Wasserfall und Hören (AM, FM, SSB, CW) eines SDR nur im Empfang, neben dem TRX; Ton des SDR während jeder Sendung stumm; Balance TRX / SDR und, mit Kopfhörer, eine Quelle pro Ohr; Zoom des Wasserfalls („Zoom − / +“ um die gehörte Frequenz, ◄ ► zum Verschieben des Fensters), Farbpalette, Breite (höchstens die in Menü 2.4 gewählte) und Antenne A / B von der Seite aus; Spots des DX-Clusters auf dem Wasserfall des SDR (einen Spot antippen: der SDR hört ihn, der TRX bewegt sich nicht); die Station verlangsamt oder unterbricht den SDR von selbst, wenn sie zu stark belastet ist; SDR IM RUHEZUSTAND, wenn seit 1 Minute niemand seine Rubrik anzeigt oder ihn hört (weniger Last und Wärme), in wenigen Sekunden geweckt beim Öffnen der Rubrik („SDR im Ruhezustand … wird geweckt“); SDR in Menü 2.4 von openRemoteTRX Console gewählt und eingestellt (Suche an allen USB-Ports und Hubs); „QSY des TRX“ auf eine am SDR gelesene Frequenz; SDR in Betrieb: unter der Frequenz des TRX eine violette Zeile „SDR“ (gehörte Frequenz, Betriebsart, Filter; Antippen öffnet die Rubrik SDR auf ihrem Wasserfall), rechts zwei Bargraphen des gehörten Tons (TRX: Antippen = stumm auf der Seite, bei jeder Verbindung zurückgesetzt; SDR: Antippen = Hören starten oder beenden, wie „Hören“), S-Meter „S-TRX“ und „S-SDR“ (S-SDR während des Hörens des SDR, angenähert „≈“, solange es nicht abgeglichen ist: SDR auf die Frequenz des TRX per „QSY TRX → SDR“, ein stabiles Signal, dann „S-SDR auf den TRX abgleichen“ in der Rubrik SDR; Abgleich im Browser gespeichert) | zuerst die SDRplay-API des Herstellers installieren, dann die Station; `trx-sdr --list` gibt die Seriennummer; `[sdr]` und „sdr“ in `[modules] run` (Menü 8.1) |

> **SDR-Empfänger: Schützen Sie seinen Eingang.** Der SDR verträgt die Leistung Ihres TRX nicht. Getrennte Antenne,
> oder Umschalter und Sequenzer, die den Eingang des SDR vor jedem Senden auf Masse legen: Das müssen Sie je nach
> Ihrer Hardware vorsehen. Die Station kann das nicht für Sie tun (ein Senden mit dem Mikrofon des Transceivers wird
> erst hinterher erkannt). Der SDR wird über seine **Seriennummer** bestimmt: Auf einem Rechner mit mehreren SDR
> tragen Sie nie die eines SDR ein, den eine andere Anwendung benutzt. Stecken Sie ihn an einen eigenen USB-Port, nie
> an den Hub des Transceivers. Die Zeile „USB-Anschlüsse“ der Karte COMPUTER (Dashboard, Menü 1.3) sagt, ob ein USB-Bus
> zu stark belastet ist oder der SDR gebremst wird; Einzelheiten und Vorgehen stehen in der Diagnose (Menü 6.1). Eine
> blaue Buchse (USB 3) beschleunigt einen USB-2-SDR nicht: Er teilt sich die 480 Mbit/s des USB-2-Teils des Rechners.

> **Sicherheit.** Was die Station empfängt, an Dritte weiterzugeben (Besucher, Hörer der Übertragung), liegt in Ihrer
> Verantwortung, besonders außerhalb der Amateurfunkbänder; standardmäßig hören Besucher und Hörer außerhalb Ihrer
> Bänder nur Stille (zwei unabhängige Einstellungen).

Je nach Transceiver können zwei Funktionen der Seite fehlen: das **KW-Spektrum des Transceivers** (nur über den
zweiten Port eines Icom wie des IC-7300MK2; sonst wird nur das Audiospektrum angezeigt) und die
**Filtervoreinstellungen FIL1/2/3** (nur bei Icom).
