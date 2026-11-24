# 4. Die Station im LAN verwenden

Das LAN ist das WLAN oder das Kabelnetz zu Hause: Telefon und Station stehen hinter demselben Router.

## 4.1 Eine feste Adresse für die Station

**Reservieren Sie** in Ihrem Router **eine IP-Adresse** für den Stations-PC (DHCP-Reservierung). Das vom Assistenten
erstellte Zertifikat trägt die Adresse des PCs: Ändert sie sich, erkennen Browser und App es nicht mehr. Nach einer
Adressänderung starten Sie den Assistenten (Menü 2.1) neu, um das Zertifikat neu zu erstellen.

Die zu verwendende Adresse wird oben in openRemoteTRX Console und von der Diagnose angezeigt.

## 4.2 Die Webseite

1. Auf dem Telefon oder einem PC: `https://<stationsadresse>:8443`
2. Der Browser meldet ein **nicht anerkanntes Zertifikat**: Das ist erwartet (von Ihrer Station erstelltes
   Zertifikat, nicht von einer Zertifizierungsstelle). „Erweitert“, dann „Weiter“. Das geschieht nur einmal pro Gerät.
3. Melden Sie sich mit dem vom Assistenten erstellten Konto an (die Eingabetaste im Passwortfeld genügt).

> **Vom Browser gespeichertes Passwort.** Chrome speichert ein Passwort **nie** auf einer Seite, deren Zertifikat
> nicht anerkannt ist, auch nicht nach „Weiter“. Die Lösung: einmal auf jedem Gerät die **Zertifizierungsstelle Ihrer
> Station** installieren (siehe unten). Danach gibt es keine Warnung mehr und das Passwort wird gespeichert.

### Die Zertifizierungsstelle der Station installieren (einmal pro Gerät)

1. Auf der Station, openRemoteTRX Console, Menü **4.4** „Zertifikat der Station“: Auswahl **1** (das Zertifikat neu
   erstellen, signiert von der Zertifizierungsstelle der Station), dann die Station neu starten, wenn die Konsole es
   vorschlägt. Der Fingerabdruck des Zertifikats ändert sich: **Koppeln Sie die Android-App neu** (Menü 4.1).
2. Öffnen Sie auf dem Gerät die Seite der Station: Tippen Sie unter dem Passwort auf **„Zertifikat der Station
   installieren“** (oder öffnen Sie `https://<stationsadresse>:8443/station-ca.crt`).
3. **Windows**: Öffnen Sie die heruntergeladene Datei, „Zertifikat installieren“, „Aktueller Benutzer“, „Alle
   Zertifikate in folgendem Speicher speichern“, **„Vertrauenswürdige Stammzertifizierungsstellen“**, Fertig stellen,
   dann bestätigen Sie die Warnung von Windows. Schließen Sie **alle** Chrome-Fenster und öffnen Sie es neu.
   Achtung: Mit „Zertifikatspeicher automatisch auswählen“ legt Windows es unter „Eigene Zertifikate“ ab, wo Chrome es
   ignoriert (Adresse weiterhin rot durchgestrichen): Wiederholen Sie die Installation und wählen Sie den Speicher
   richtig.
4. **Android**: Einstellungen, Sicherheit (oder „Sicherheit und Datenschutz“), Weitere Sicherheitseinstellungen, Vom
   Speicher installieren (oder „Verschlüsselung und Anmeldedaten“), **„CA-Zertifikat“**, wählen Sie die
   heruntergeladene Datei und bestätigen Sie. Öffnen Sie Chrome neu.
5. Öffnen Sie die Seite: keine Warnung mehr; melden Sie sich an, Chrome bietet an, das Passwort zu speichern.

> Diese Zertifizierungsstelle kann **nur** private Adressen (LAN, VPN) und die Namen Ihrer Station bestätigen: Selbst
> wenn ihr Schlüssel gestohlen würde, ließe sich damit auf Ihren Geräten keine andere Website (Bank…) nachahmen.

Was Sie sehen sollten: Frequenz und Betriebsart, die dem Transceiver folgen, S-Meter, Empfangston (tippen Sie auf
die Ton-Schaltfläche, wenn der Browser ihn blockiert hat).

Zum **Senden** braucht die Seite das **Mikrofon**: Der Browser fragt beim ersten Senden danach. Er bietet es nur über
HTTPS an, daher das Zertifikat.

> **Sicherheit.** Der PTT ist ein **Umschalter**: ein Druck zum Senden, ein Druck zurück auf Empfang. Der angezeigte
> Zustand ist der von der Station bestätigte, nie eine Vermutung. **STOP** schaltet jederzeit ab. **STOP 3 Sekunden
> gedrückt halten** (Countdown unter dem Wort STOP) öffnet ein Fenster: „Trennen“ oder „TRX aus der Ferne
> ausschalten“ (mit einer Bestätigung; nur wenn das Fern-Einschalten in Betrieb ist, Menü 2.8). Eine verborgene Seite
> (anderer Tab, gesperrter Bildschirm) beendet das Senden.
>
> **Transceiver ausgeschaltet.** Ein rotes Banner „FUNKGERÄT AUS“ zeigt es an. Ist das Fern-Einschalten in Betrieb,
> schaltet Ihre Verbindung den Transceiver von selbst ein: Ein Fenster zeigt die Schritte (serielle Ports geprüft,
> Befehl, Start, erneutes Auslesen) und im Fehlerfall eine klare Meldung mit „Erneut versuchen“ und „Ohne Funkgerät
> fortfahren“; die Schaltfläche „Funkgerät einschalten“ im Banner tut dasselbe. Eine automatische Neuverbindung
> schaltet den Transceiver nie ein. Die App tut dasselbe (ihr STOP schaltet schon beim Drücken ab); im Auto zeigt
> Android Auto „FUNKGERÄT AUS“ oder „FUNKGERÄT STARTET…“ als Titel.

## 4.3 Mehrere Geräte, mehrere Benutzer

Einfache Regel: **ein Konto pro Gerät**, benannt nach dem Gerät (`PC`, `S25`, `tablet`…), auch wenn sie alle Ihnen
gehören. Dasselbe Konto auf einem zweiten Gerät geöffnet **schließt die Verbindung des ersten** (und beendet dessen
Sendung, falls es sendete). Mit einem Konto pro Gerät weiß die Station, welches sendet, und Sie können ein einzelnes
Gerät entfernen (verlorenes Telefon), ohne die anderen anzufassen.

Alles geschieht in Menü **4.3 „Operator-Konten“** von openRemoteTRX Console:

- ein Konto **hinzufügen**: Benutzername, Passwort (Eingabetaste = ein starkes Passwort wird erzeugt, notieren Sie
  es), dann der **Kopplungs-QR-Code** dieses Kontos für die App;
- ein **Passwort ändern** (ein vergessenes Passwort wird ersetzt: Die Station kennt es nicht im Klartext);
- ein Konto **deaktivieren** (verlorenes oder verliehenes Telefon), dann wieder aktivieren;
- ein Konto **löschen**.

Die Station übernimmt die Änderungen in wenigen Sekunden, ohne Neustart; die Verbindung eines deaktivierten,
gelöschten Kontos oder eines Kontos mit geändertem Passwort wird sofort geschlossen. Das letzte aktive Operator-Konto
kann weder deaktiviert noch gelöscht werden. Es kann immer nur eine Person senden. Für Zuhörer ganz ohne Befehle
nehmen Sie besser **Besucher** (Menü 4.2, Teil 9).

## 4.4 Die Android-App

Die App („openRemoteTRX“, Android 10 oder neuer) bringt, was die Seite nicht kann: Senden, das bei ausgeschaltetem
Bildschirm weiterläuft, Taste eines Headsets, Android Auto, Fahrmodus.

1. Installieren Sie die App (Test auf Einladung, Teil 0).
2. Auf der Station, Menü **4.1**: openRemoteTRX Console zeigt die Adresse, die Konten, den Fingerabdruck des
   Zertifikats und einen **QR-Code** (ohne Passwort).
3. In der App: „**QR-Code der Station scannen**“. Adresse, Benutzername und Fingerabdruck werden ausgefüllt; geben
   Sie das Passwort ein.
4. Melden Sie sich an: dieselbe Prüfung wie bei der Seite (Frequenz, Empfangston), dann ein Sendetest an der
   Dummy-Load mit STOP.

Der Fingerabdruck des Zertifikats schützt die Verbindung: Die App lehnt eine Station ab, deren Zertifikat sich
geändert hat. Nach einem neuen Zertifikat (Adressänderung) wiederholen Sie die Kopplung.

> **Sicherheit.** Im Auto ist der Touch-PTT des Telefons ausgeblendet (Fahrmodus): Verwenden Sie Android Auto, die
> Sprachsteuerung oder die Lenkradtasten und beachten Sie die Straßenverkehrsordnung.
