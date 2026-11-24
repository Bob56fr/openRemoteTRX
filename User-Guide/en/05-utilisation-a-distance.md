# 5. Using the station remotely (outside the local network)

The station does not manage the network: it listens on an address and a port, and protects access with a username
and password. You choose how your phone reaches it from outside. The full technical guide:
https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant.md

## 5.1 Choose: VPN or open port

| | A. VPN (recommended) | B. Open port on the box |
|---|---|---|
| Principle | a VPN links the phone to the station's network | the box forwards an Internet port to the station |
| Examples | WireGuard (often built into the box), Tailscale, OpenVPN | box + domain name + recognised certificate |
| Visible from the Internet | nothing | the login page |
| Audio (WebRTC, UDP) | goes through easily | often goes through, **not always** (strict box, address shared by the provider) |

Choose the VPN if in doubt: nothing is exposed, and the audio goes through.

## 5.2 Option A: VPN

1. Install the VPN of your choice: server on the box or on the station PC, client on the phone.
   For Tailscale, a dedicated guide: https://github.com/Bob56fr/openRemoteTRX/blob/main/docs/acces-distant-tailscale.md
2. **One VPN profile per device**, never shared. Two devices on the same profile steal the link from each other:
   dropouts every 15 to 30 seconds.
3. If the VPN lands **on your local network** (VPN of the box): nothing to change on the station, use the same
   address as at home. If the VPN gives the station PC **a separate address** (Tailscale, WireGuard on the PC): run
   the wizard again (menu 2.1, network access) so that the certificate also covers this address, then pair the app
   again (menu 4.1).
4. On the phone, on 4G, VPN active: open the same page `https://<station-address>:8443`.

On Android, only one VPN can be active at a time. With **Android Auto**, route only the station's network through
the tunnel (not all traffic), otherwise the car refuses the link: detailed settings in the technical guide, section
“Android Auto et VPN”.

## 5.3 Option B: open port on the box

For those who know their box and certificates.

1. **Check that it is possible**: compare the “WAN” address of your box with the one given by a “what is my IP
   address” website. If they differ, your provider shares your address (CGNAT): no port can be opened, use a VPN.
2. A **domain name** pointing to your box (dynamic DNS if the address changes).
3. A **recognised certificate**: the simplest is an HTTPS proxy (Caddy) on the station PC, which obtains and renews a
   Let's Encrypt certificate by itself; the station then keeps listening locally. Example and settings in the
   technical guide, section “Option B”.
4. On the box, forward port 443 (TCP) to the station PC.

> **Safety.** With an open port, the **password is your only barrier**: long and unique for each account. The
> station slows down attempts (5 failures per minute and per origin, 30 per quarter of an hour and per account), but
> a stolen password allows transmitting in your allowed bands. The transmission safeguards stay active in all cases,
> and so does the transceiver's transmit timer (part 1).

## 5.4 Tests from outside

Phone **on 4G** (Wi-Fi off), dummy load on the transceiver:

1. The page opens (option B: padlock without warning).
2. A wrong password is refused.
3. The right password connects: frequency, S-meter, **received audio**.
4. Transmission on the dummy load: PTT, then **STOP**; then transmit and switch to airplane mode: back to receive.
5. If the page opens but the audio does not establish: UDP is not getting through (option B): switch to the VPN.

In case of repeated dropouts, menu 6.4 (network quality) says which segment fails: phone, mobile network, tunnel,
box or station.
