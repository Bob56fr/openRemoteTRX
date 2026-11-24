# 5. Die Station aus der Ferne verwenden (außerhalb des LAN)

Die Station verwaltet das Netzwerk nicht: Sie hört auf einer Adresse und einem Port und schützt den Zugang mit
Benutzername und Passwort. Sie wählen selbst, wie Ihr Telefon sie von außen erreicht. Die vollständige technische
Anleitung: https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant.md

## 5.1 Wählen: VPN oder Portfreigabe

| | A. VPN (empfohlen) | B. Portfreigabe am Router |
|---|---|---|
| Prinzip | ein VPN verbindet das Telefon mit dem Netzwerk der Station | der Router leitet einen Port aus dem Internet an die Station weiter |
| Beispiele | WireGuard (oft im Router integriert), Tailscale, OpenVPN | Router + Domainname + anerkanntes Zertifikat |
| Aus dem Internet sichtbar | nichts | die Anmeldeseite |
| Ton (WebRTC, UDP) | geht einfach durch | geht oft durch, **nicht immer** (strenger Router, geteilte Adresse des Providers) |

Wählen Sie im Zweifel das VPN: Nichts ist offen, und der Ton geht durch.

## 5.2 Option A: VPN

1. Installieren Sie das VPN Ihrer Wahl: Server auf dem Router oder auf dem Stations-PC, Client auf dem Telefon.
   Für Tailscale gibt es eine eigene Anleitung: https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant-tailscale.md
2. **Ein VPN-Profil pro Gerät**, nie geteilt. Zwei Geräte mit demselben Profil stehlen sich gegenseitig die
   Verbindung: Abbrüche alle 15 bis 30 Sekunden.
3. Kommt das VPN **in Ihrem LAN** an (VPN des Routers): An der Station ist nichts zu ändern, verwenden Sie dieselbe
   Adresse wie zu Hause. Gibt das VPN dem Stations-PC **eine eigene Adresse** (Tailscale, WireGuard auf dem PC):
   Starten Sie den Assistenten neu (Menü 2.1, Netzwerkzugang), damit das Zertifikat auch diese Adresse abdeckt, und
   wiederholen Sie dann die Kopplung der App (Menü 4.1).
4. Öffnen Sie auf dem Telefon, über 4G, mit aktivem VPN dieselbe Seite `https://<stationsadresse>:8443`.

Unter Android kann immer nur ein VPN gleichzeitig aktiv sein. Mit **Android Auto** leiten Sie nur das Netzwerk der
Station durch den Tunnel (nicht den ganzen Verkehr), sonst lehnt das Auto die Verbindung ab: ausführliche
Einstellungen in der technischen Anleitung, Abschnitt „Android Auto et VPN“.

## 5.3 Option B: Portfreigabe am Router

Nur für alle, die ihren Router und Zertifikate kennen.

1. **Prüfen Sie, ob es möglich ist**: Vergleichen Sie die „WAN“-Adresse Ihres Routers mit der, die eine Website „Wie
   ist meine IP-Adresse“ anzeigt. Unterscheiden sie sich, teilt Ihr Provider Ihre Adresse (CGNAT): Kein Port kann
   geöffnet werden, nehmen Sie ein VPN.
2. Ein **Domainname**, der auf Ihren Router zeigt (dynamisches DNS, wenn sich die Adresse ändert).
3. Ein **anerkanntes Zertifikat**: Am einfachsten ist ein HTTPS-Proxy (Caddy) auf dem Stations-PC, der selbst ein
   Let's-Encrypt-Zertifikat bezieht und erneuert; die Station hört dann nur lokal. Beispiel und Einstellungen in der
   technischen Anleitung, Abschnitt „Option B“.
4. Leiten Sie am Router den Port 443 (TCP) an den Stations-PC weiter.

> **Sicherheit.** Mit einer Portfreigabe ist das **Passwort Ihre einzige Barriere**: lang und für jedes Konto
> einzigartig. Die Station bremst Versuche (5 Fehlschläge pro Minute und Herkunft, 30 pro Viertelstunde und Konto),
> aber ein gestohlenes Passwort erlaubt das Senden in Ihren erlaubten Bändern. Die Sendesicherheiten bleiben in allen
> Fällen aktiv, und die Sendezeitbegrenzung des Transceivers (Teil 1) ebenfalls.

## 5.4 Tests von außen

Telefon **über 4G** (WLAN aus), Dummy-Load am Transceiver:

1. Die Seite öffnet sich (Option B: Schloss ohne Warnung).
2. Ein falsches Passwort wird abgelehnt.
3. Das richtige Passwort verbindet: Frequenz, S-Meter, **Empfangston**.
4. Senden an der Dummy-Load: PTT, dann **STOP**; dann Senden und Wechsel in den Flugmodus: zurück auf Empfang.
5. Öffnet sich die Seite, aber der Ton kommt nicht zustande: Dann geht UDP nicht durch (Option B): Wechseln Sie zum
   VPN.

Bei wiederholten Abbrüchen sagt Menü 6.4 (Netzwerkqualität), welcher Abschnitt versagt: Telefon, Mobilfunknetz,
Tunnel, Router oder Station.
