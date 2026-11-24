# 1. Den Transceiver vorbereiten

Station **ausgeschaltet**, nichts angeschlossen: Jetzt ist der Moment, den Transceiver einzustellen. Die Einzelheiten
der Menüs Ihres Transceivers stehen in seinem Datenblatt ([Icom IC-7300MK2](postes/ic7300mk2.md),
[Yaesu FTDX10](postes/ftdx10.md)); für einen anderen Transceiver sein Handbuch und die Tabelle „Je nach Marke“ im
[Schnellstart](demarrage-rapide.md). Dieser Teil sagt, in welcher Reihenfolge Sie vorgehen.

## 1.1 Den USB-Treiber installieren (nur Windows)

Unter Windows wird der USB-Treiber des Transceivers (der seines Herstellers: „Icom USB Driver“, Silicon Labs CP210x
bei Yaesu…) **vor** dem Anschließen des USB-Kabels installiert; sonst kann Windows einen falschen Treiber
installieren. Name, Mindestversion und Vorgehen stehen im Datenblatt des Transceivers unter „USB-Treiber“, sonst auf
der Website des Herstellers.

Unter Debian und auf einem Raspberry Pi ist nichts zu installieren: Der Kernel erkennt den Transceiver von selbst.

## 1.2 Anschließen

1. Antenne abgeklemmt, **Dummy-Load** an der verwendeten Antennenbuchse.
2. USB-Kabel zwischen Transceiver und PC.
3. Schalten Sie den Transceiver ein (langer Druck auf ON/OFF).

Der PC sieht dann einen oder zwei **serielle Ports** und eine **Soundkarte**. Das Datenblatt des Transceivers sagt,
welcher für die Steuerung dient (IC-7300MK2: der erste, der zweite dient dem KW-Spektrum; FTDX10: der „Enhanced COM
Port“, der „Standard“ wird nicht benutzt).

<!-- onglets -->
#### Debian

Nichts zu notieren: Der Assistent erkennt den richtigen Port selbst. Um ihn zu sehen: `ls -l /dev/serial/by-id/` in
einem Terminal (ein stabiler Name je Port, der sich von einer USB-Buchse zur anderen nicht ändert).

#### Raspberry Pi

Wie unter Debian. Stecken Sie das Kabel des Transceivers **direkt** in einen USB-Port des Pi (die blauen USB-3-Ports
gehen auch); einen Hub nur, wenn er eine eigene Stromversorgung hat: Der Pi liefert nicht genug Strom für mehrere
Geräte.

#### Windows

Geräte-Manager > Anschlüsse (COM & LPT): Notieren Sie die COM-Nummer des Steuerports.
<!-- /onglets -->

## 1.3 Die Menüs des Transceivers einstellen

Stellen Sie die Menüs ein, die im Datenblatt Ihres Transceivers im Abschnitt „Einzustellende Menüs“ aufgeführt sind
(sonst in seinem Handbuch). Sie sind unverzichtbar:

- **CAT-Baudrate** gleich der der Station (im Assistenten gewählt);
- **Stimme über USB**: sonst moduliert der Transceiver mit seinem eigenen Mikrofon, also mit den Geräuschen im Raum.
  Bei einem Icom (IC-7300MK2): MENU > SET > Connectors > MOD Input > **DATA MOD = USB** (die Station sendet nur in
  einer Datenbetriebsart); der Transceiver akzeptiert die USB-Buchse nur in DATA MOD **oder** DATA OFF MOD. Ist der
  zweite Port eingerichtet, prüft die Station dies bei jeder Verbindung und warnt Sie, wenn er nicht auf USB steht;
- **keine RTS/DTR-Leitung** für PTT oder CW: sonst kann der Transceiver beim Hochfahren des PCs auf Senden gehen;
- **VOX aus**: Ein eingeschaltetes VOX lässt den Transceiver bei einem Geräusch im Raum senden, ganz ohne Befehl. Die Station prüft dies bei jeder Verbindung eines Operators und **schaltet es ab**, wenn es eingeschaltet ist (Meldung im Protokoll der Seite, Code ORT-5034). Bei manchen Geräten bleibt es in einer Betriebsart eingeschaltet, während es in einer anderen aus ist (beim IC-7300MK2 gesehen: aus in der Datenbetriebsart, noch eingeschaltet in Telefonie);
- **eingebauter Antennentuner** (wenn die Antenne über ihn läuft): Die Abstimmung muss beim Tasten auf einer neuen
  Frequenz von selbst starten. Beim IC-7300MK2: MENU > SET > Function > Tuner, **[TUNER] Switch = Auto** (Zustand
  des Tuners je Band gespeichert) und **PTT Start = ON**. Beantworten Sie die Tuner-Frage des Assistenten mit „ja“:
  Die Station prüft diese Einstellungen dann bei jeder Verbindung und warnt Sie, wenn sie falsch sind (sie ändert sie
  nie). Außerhalb der Amateurfunkbänder garantiert der Transceiver die Abstimmung per PTT nicht. Übersteigt das SWR
  während einer Sendung länger als eine Sekunde 2, zeigt die Seite ein rotes Banner und piept (sie schaltet nicht
  ab);
- **Sendezeitbegrenzung des Transceivers** (TX TIME OUT TIMER): eine zweite Sicherheit, unabhängig von der Station.
  Stellen Sie sie ein (3 min empfohlen): Fallen Station, Netzwerk oder PC während einer Sendung aus, schaltet sie ab.
  Bei einem Transceiver, dessen Auslesen qualifiziert ist (IC-7300MK2), liest die Station sie bei jeder Verbindung
  und warnt Sie, wenn sie auf OFF steht; bei den anderen kann sie sie nicht prüfen.

> **Sicherheit.** Eine zusätzliche Sicherheit kostet nichts: Stellen Sie im Transceiver auch eine vernünftige
> **Höchstleistung** ein (HF MAX POWER). Die Station kann sie nicht überschreiten, was auch geschieht.

## 1.4 Ton des PCs

Die Soundkarte des Transceivers darf **nie** das Standard-Audiogerät des PCs sein, sonst gehen die Töne des Desktops
an den Transceiver (und der Desktop belegt die Karte):

<!-- onglets -->
#### Debian

*Einstellungen > Audio*: als Ausgabe die Lautsprecher des PCs, als Eingabe sein Mikrofon.

#### Raspberry Pi

Ohne Desktop (Raspberry Pi OS Lite): nichts zu tun, kein Programm belegt die Karte des Transceivers. Mit Desktop:
wie unter Debian, in den Audioeinstellungen der oberen Leiste. Die Soundkarte des Pi selbst („Headphones“, „HDMI“)
wird von der Station nicht benutzt.

#### Windows

*Einstellungen > System > Sound*: als Ausgabe die Lautsprecher des PCs, als Eingabe sein Mikrofon; unter „Weitere
Soundeinstellungen“ ist die Karte des Transceivers weder „Standardgerät“ noch „Standardkommunikationsgerät“;
Soundschema „Keine Sounds“. Die Einzelheiten stehen in der Windows-Anleitung, die dem Paket beiliegt.
<!-- /onglets -->
