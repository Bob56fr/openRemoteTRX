# 6. Eine Station ohne Aufsicht

Eine ferngesteuerte Station läuft die meiste Zeit ohne jemanden daneben. Dieser Teil bereitet diesen Fall vor.

## 6.1 Die Alarme auf Ihrem Telefon (ntfy)

Der Supervisor der Station kann Ihnen Benachrichtigungen schicken: aus Sicherheitsgründen beendetes Senden, Ausfall,
Sicherheitsabschaltung, fast voller Speicher oder fast volle Festplatte, Verbindungsabbruch und jede Stunde eine
Meldung „Station in Betrieb“ ohne Klingelton (kommt sie nicht mehr, ist die Station oder ihre Verbindung ausgefallen).

1. Installieren Sie die App **ntfy** auf dem Telefon.
2. Wählen Sie einen **langen, nicht zu erratenden Themennamen** (zum Beispiel 20 zufällige Buchstaben und Ziffern):
   Auf dem öffentlichen Server ntfy.sh liest jeder die Meldungen, der den Namen kennt.
3. Abonnieren Sie dieses Thema in der ntfy-App.
4. Auf der Station, Menü **3.5** „Alarme auf dem Telefon“: Auswahl 1, fügen Sie die Adresse
   `https://ntfy.sh/<ihr-thema>` ein, speichern Sie, bestätigen Sie den Neustart. Der Bildschirm zeigt die Adresse nie
   vollständig.
5. Prüfen Sie: Auswahl 4, „Jetzt einen Testalarm senden“; das Telefon muss sofort klingeln (Code ORT-8025). Danach
   kommt die Meldung „Station in Betrieb“ jede Stunde (Auswahl 3, um diesen Rhythmus zu ändern).

Jeder Alarm trägt einen Code „ORT-NNNN“ mit einem Link zu seiner Erklärung (Teil 8). Zwei Alarme kommen beim Neustart
nach einem nicht sauberen Stopp: **ORT-8030** (Debian, Raspberry Pi: Der Rechner ist abrupt stehen geblieben,
Stromausfall oder Absturz) und **ORT-8031** (nur der Supervisor ist stehen geblieben); jeder gibt die Uhrzeit des
letzten Lebenszeichens an. Ein normaler Stopp (Menü 1.2, Herunterfahren des PCs) sendet nichts.

## 6.2 Die Sicherheitsabschaltung

Nach wiederholten Ausfällen, die Neustarts nicht behoben haben, **schaltet der Supervisor die Station in die
Sicherheitsabschaltung**: Transceiver auf Empfang, Zugang gesperrt, Alarm gesendet. Die Sicherheitsabschaltung
**überdauert Neustarts**: Sie müssen die Ursache finden (Menüs 6.1 und 6.2) und sie dann über Menü **1.4** aufheben.

## 6.3 Nach einem Stromausfall

| Element | Einzustellen |
|---|---|
| PC | im BIOS / UEFI: „Restore on AC power loss“ = **Power On** (der Name hängt vom Mainboard ab) |
| Raspberry Pi | nichts: er startet, sobald der Strom zurückkommt |
| Station unter Debian oder Raspberry Pi | nichts: sie startet mit dem Rechner, ohne Anmeldung |
| Station unter Windows | sie startet bei der **Anmeldung**: ohne automatische Anmeldung Ihrer Sitzung bleibt sie gestoppt |
| Transceiver | die meisten Geräte schalten sich **nicht** von selbst wieder ein. Die Station kann ihn über CAT einschalten (Menü **2.8**, standardmäßig außer Betrieb, mit einem Test aus- / einschalten): Ihre Verbindung von der Seite oder der App schaltet ihn ein |
| Router | schaltet sich von selbst wieder ein; prüfen Sie, dass das VPN es auch tut |

Eine **USV** für PC, Router und Netzteil des Transceivers vermeidet die meisten dieser Fälle.

## 6.4 Schutz der Hardware

- **Blitz**: Eine Station ohne Menschen in der Nähe ist exponiert. Blitzschutz am Antennenkabel, und Antenne geerdet
  oder abgeklemmt, wenn ein Gewitter angekündigt ist.
- **Leistung**: Die Obergrenze des Transceivers (HF MAX POWER, Teil 1) bleibt die letzte Barriere.
- **Sendezeitbegrenzung des Transceivers** (TX TIME OUT TIMER): auf 3 min eingestellt, schaltet sie ab, selbst wenn
  alles andere versagt hat.
- **Temperatur**: Der Supervisor überwacht den Prozessor des PCs und alarmiert, wenn er eine Minute lang über 70 °C
  bleibt (eine Spitze von einigen Sekunden zählt nicht); der Alarm sagt, welche Programme heizten. Unter Debian und
  auf einem Pi wird der Verlauf der letzten 24 h (eine Messung alle 10 s) dem Fehlerbericht (Menü 6.3) beigefügt. Auf
  einem Pi ist ein Lüfter unverzichtbar. Die Temperatur des Transceivers kann die Station bei den getesteten Geräten
  (IC-7300MK2, FTDX10) nicht lesen: für gute Belüftung um den Transceiver sorgen.
- **Operator vor Ort**: Benutzt jemand den Transceiver vor Ort, ist das Senden aus der Ferne während seiner Sendung
  und dann 2 Minuten lang gesperrt; die Station unterbricht ihn deswegen nie. Eine Sendung mit dem Mikrofon wird vom
  absoluten TOT (135 s) abgeschaltet, außer der Operator hat den Transceiver (Lautstärke, Frequenz, Betriebsart,
  Verlassen der DATA-Betriebsart…) in den 2 Minuten vor dem Sprechen oder während des Sprechens berührt: Die Station
  weiß dann, dass er anwesend ist, und lässt ihn bis zu 5 Minuten sprechen (`local_tx_max_s`), dazwischen mit einem
  einfachen Alarm. Ist die Sendezeitbegrenzung des Transceivers kürzer eingestellt, schaltet sie vorher ab. Diese
  Einstellungen stehen in Menü **3.4** „Operator vor Ort“: Behalten Sie „Geteilte Station“; sonst führt ein gedrückt
  gehaltenes Mikrofon zur Sicherheitsabschaltung.
