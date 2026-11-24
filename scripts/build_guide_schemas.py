# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Schémas de la partie 0 du guide de l'opérateur, en thème clair, dans les quatre langues :
User-Guide/<langue>/images/reseau.svg (appareils, 4G / 5G, box et VPN, réseau local, station, poste) et briques.svg
(l'intérieur du PC de la station, sur fond ambre). Un seul dessin, les textes de chaque langue dans T : un changement
de dessin ou de texte se fait ici, puis

    python scripts/build_guide_schemas.py
    python scripts/build_user_guide.py

(les tests du guide vérifient que les schémas écrits sont ceux que fabrique ce script).
"""
from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "User-Guide"
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"

RESEAU = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 900" width="640" height="900" role="img" aria-labelledby="r-titre r-desc" font-family="{font}">
  <title id="r-titre">{r_title}</title>
  <desc id="r-desc">{r_desc}</desc>
  <defs>
    <marker id="r-fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#6b7a8f"/></marker>
    <marker id="r-flv" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7a56c2"/></marker>
  </defs>
  <rect width="640" height="900" rx="14" fill="#ffffff"/>

  <!-- Ailleurs -->
  <rect x="12" y="12" width="616" height="178" rx="12" fill="#f4f1fb" stroke="#cfc3ea"/>
  <text x="30" y="40" fill="#5b4a8a" font-size="14" font-weight="700" letter-spacing=".6">{away}</text>
  <rect x="30" y="58" width="180" height="80" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="120" y="92" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{laptop}</text>
  <text x="120" y="116" fill="#55657a" font-size="14" text-anchor="middle">{browser}</text>
  <rect x="230" y="58" width="180" height="80" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="320" y="92" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{tablet}</text>
  <text x="320" y="116" fill="#55657a" font-size="14" text-anchor="middle">{browser_or_app}</text>
  <rect x="430" y="58" width="180" height="80" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="520" y="92" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{phone}</text>
  <text x="520" y="116" fill="#55657a" font-size="14" text-anchor="middle">{app_auto}</text>
  <text x="320" y="170" fill="#5b4a8a" font-size="14" text-anchor="middle">{vpn_profile}</text>

  <line x1="120" y1="140" x2="230" y2="216" stroke="#6b7a8f" stroke-width="2"/>
  <line x1="320" y1="140" x2="320" y2="216" stroke="#6b7a8f" stroke-width="2"/>
  <line x1="520" y1="140" x2="410" y2="216" stroke="#6b7a8f" stroke-width="2"/>

  <!-- Internet -->
  <rect x="140" y="216" width="360" height="60" rx="30" fill="#f7f8fa" stroke="#8795a8" stroke-width="2"/>
  <text x="320" y="243" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">Internet</text>
  <text x="320" y="264" fill="#55657a" font-size="14" text-anchor="middle">{mobile}</text>

  <!-- Maison -->
  <rect x="12" y="300" width="616" height="588" rx="12" fill="#eef4fb" stroke="#b8cbe0"/>
  <text x="30" y="328" fill="#2c5d8f" font-size="14" font-weight="700" letter-spacing=".6">{home}</text>
  <rect x="170" y="380" width="300" height="78" rx="10" fill="#fff" stroke="#7a56c2" stroke-width="2"/>
  <text x="320" y="412" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{box}</text>
  <text x="320" y="436" fill="#55657a" font-size="14" text-anchor="middle">{box_sub}</text>

  <!-- Tunnel VPN -->
  <line x1="320" y1="278" x2="320" y2="376" stroke="#7a56c2" stroke-width="5" stroke-dasharray="10 6" marker-end="url(#r-flv)"/>
  <text x="334" y="314" fill="#5b4a8a" font-size="14" font-weight="700">{tunnel}</text>
  <text x="334" y="334" fill="#55657a" font-size="13">{tunnel_ex}</text>
  <text x="334" y="352" fill="#55657a" font-size="13">{port_note}</text>

  <line x1="320" y1="460" x2="320" y2="500" stroke="#6b7a8f" stroke-width="2"/>
  <line x1="90" y1="500" x2="560" y2="500" stroke="#6b7a8f" stroke-width="3"/>
  <text x="330" y="490" fill="#55657a" font-size="13">{cable_wifi}</text>
  <line x1="180" y1="500" x2="180" y2="542" stroke="#6b7a8f" stroke-width="2" marker-end="url(#r-fl)"/>
  <line x1="485" y1="500" x2="485" y2="542" stroke="#6b7a8f" stroke-width="2" marker-end="url(#r-fl)"/>
  <text x="190" y="526" fill="#55657a" font-size="13">{cable_advised}</text>

  <!-- PC de la station -->
  <rect x="30" y="546" width="300" height="164" rx="12" fill="#fff1d6" stroke="#d99a2b" stroke-width="2.5"/>
  <text x="180" y="580" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{station_pc}</text>
  <text x="180" y="604" fill="#55657a" font-size="14" text-anchor="middle">{systems}</text>
  <text x="180" y="634" fill="#1d2733" font-size="14" text-anchor="middle">{page_audio}</text>
  <text x="180" y="656" fill="#1d2733" font-size="14" text-anchor="middle">{station_parts}</text>
  <text x="180" y="684" fill="#8a5a0a" font-size="13" text-anchor="middle">{detail_next}</text>

  <!-- Terminaux du réseau local -->
  <text x="485" y="560" fill="#2c5d8f" font-size="13" font-weight="700" text-anchor="middle">{home_too}</text>
  <rect x="380" y="570" width="210" height="42" rx="9" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="485" y="597" fill="#1d2733" font-size="15" font-weight="600" text-anchor="middle">{pc_browser}</text>
  <rect x="380" y="620" width="210" height="42" rx="9" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="485" y="647" fill="#1d2733" font-size="15" font-weight="600" text-anchor="middle">{tablet}</text>
  <rect x="380" y="670" width="210" height="42" rx="9" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="485" y="697" fill="#1d2733" font-size="15" font-weight="600" text-anchor="middle">{phone_wifi}</text>

  <!-- Poste -->
  <line x1="180" y1="712" x2="180" y2="772" stroke="#1d2733" stroke-width="3" marker-end="url(#r-fl)"/>
  <text x="192" y="738" fill="#1d2733" font-size="13" font-weight="600">{usb}</text>
  <text x="192" y="756" fill="#55657a" font-size="13">{usb_sub}</text>
  <rect x="30" y="776" width="300" height="94" rx="12" fill="#fff" stroke="#1d2733" stroke-width="2.5"/>
  <text x="180" y="812" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{rig}</text>
  <text x="180" y="836" fill="#55657a" font-size="14" text-anchor="middle">{antenna}</text>
  <text x="180" y="856" fill="#55657a" font-size="14" text-anchor="middle">{for_tests}</text>

  <rect x="380" y="776" width="210" height="94" rx="12" fill="#f7f8fa" stroke="#b8cbe0"/>
  <text x="485" y="806" fill="#1d2733" font-size="14" font-weight="700" text-anchor="middle">{same_address}</text>
  <text x="485" y="828" fill="#55657a" font-size="13" text-anchor="middle">{home_and_vpn}</text>
  <text x="485" y="850" fill="#2f74c0" font-size="13" text-anchor="middle">https://&lt;station&gt;:8443</text>
</svg>
"""

BRIQUES = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 820" width="640" height="820" role="img" aria-labelledby="b-titre b-desc" font-family="{font}">
  <title id="b-titre">{b_title}</title>
  <desc id="b-desc">{b_desc}</desc>
  <defs>
    <marker id="b-fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#6b7a8f"/></marker>
    <marker id="b-flr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c8402f"/></marker>
  </defs>
  <rect width="640" height="820" rx="14" fill="#ffffff"/>

  <text x="20" y="32" fill="#2c5d8f" font-size="14" font-weight="700" letter-spacing=".6">{user_side}</text>
  <rect x="20" y="44" width="285" height="88" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="162" y="78" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{browser_t}</text>
  <text x="162" y="104" fill="#55657a" font-size="14" text-anchor="middle">{devices}</text>
  <rect x="335" y="44" width="285" height="88" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="477" y="78" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{android_app}</text>
  <text x="477" y="104" fill="#55657a" font-size="14" text-anchor="middle">{android_auto}</text>

  <line x1="162" y1="134" x2="162" y2="166" stroke="#6b7a8f" stroke-width="2" marker-start="url(#b-fl)" marker-end="url(#b-fl)"/>
  <line x1="477" y1="134" x2="477" y2="166" stroke="#6b7a8f" stroke-width="2" marker-start="url(#b-fl)" marker-end="url(#b-fl)"/>
  <rect x="95" y="168" width="450" height="58" rx="29" fill="#f7f8fa" stroke="#8795a8" stroke-width="2"/>
  <text x="320" y="193" fill="#1d2733" font-size="16" font-weight="700" text-anchor="middle">{net}</text>
  <text x="320" y="213" fill="#55657a" font-size="13" text-anchor="middle">{net_sub}</text>
  <line x1="162" y1="228" x2="162" y2="306" stroke="#6b7a8f" stroke-width="2" marker-start="url(#b-fl)" marker-end="url(#b-fl)"/>
  <line x1="477" y1="228" x2="477" y2="306" stroke="#6b7a8f" stroke-width="2" marker-start="url(#b-fl)" marker-end="url(#b-fl)"/>

  <!-- Cadre du PC de la station : fond ambre -->
  <rect x="20" y="246" width="600" height="420" rx="14" fill="#fff1d6" stroke="#d99a2b" stroke-width="2.5"/>
  <text x="36" y="272" fill="#8a5a0a" font-size="14" font-weight="700" letter-spacing=".6">{station_caps}</text>
  <text x="36" y="292" fill="#8a5a0a" font-size="13">{systems}</text>

  <rect x="40" y="308" width="560" height="92" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2.5"/>
  <text x="320" y="338" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{gateway}</text>
  <text x="320" y="362" fill="#55657a" font-size="14" text-anchor="middle">{gw1}</text>
  <text x="320" y="382" fill="#55657a" font-size="14" text-anchor="middle">{gw2}</text>

  <line x1="160" y1="402" x2="160" y2="444" stroke="#6b7a8f" stroke-width="2" marker-end="url(#b-fl)"/>
  <text x="170" y="428" fill="#55657a" font-size="13">{commands}</text>
  <rect x="40" y="446" width="250" height="84" rx="10" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="165" y="476" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">rigctld (Hamlib)</text>
  <text x="165" y="498" fill="#55657a" font-size="13" text-anchor="middle">{rig1}</text>
  <text x="165" y="516" fill="#55657a" font-size="13" text-anchor="middle">{rig2}</text>

  <rect x="350" y="446" width="250" height="84" rx="10" fill="#fff" stroke="#c8402f" stroke-width="2"/>
  <text x="475" y="476" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{supervisor}</text>
  <text x="475" y="498" fill="#55657a" font-size="13" text-anchor="middle">{sup1}</text>
  <text x="475" y="516" fill="#55657a" font-size="13" text-anchor="middle">{sup2}</text>
  <line x1="520" y1="444" x2="520" y2="404" stroke="#c8402f" stroke-width="2" marker-end="url(#b-flr)"/>
  <text x="510" y="428" fill="#c8402f" font-size="13" text-anchor="end">{watch}</text>
  <line x1="348" y1="500" x2="294" y2="500" stroke="#c8402f" stroke-width="2" marker-end="url(#b-flr)"/>
  <text x="321" y="490" fill="#c8402f" font-size="12" font-weight="700" text-anchor="middle">T 0</text>

  <rect x="40" y="556" width="250" height="90" rx="10" fill="#fff" stroke="#2e8b57" stroke-width="2"/>
  <text x="165" y="592" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">station.toml</text>
  <text x="165" y="616" fill="#55657a" font-size="13" text-anchor="middle">{config}</text>
  <rect x="350" y="556" width="250" height="90" rx="10" fill="#fff" stroke="#2e8b57" stroke-width="2"/>
  <text x="475" y="584" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{tools}</text>
  <text x="475" y="606" fill="#55657a" font-size="13" text-anchor="middle">{tools1}</text>
  <text x="475" y="624" fill="#55657a" font-size="13" text-anchor="middle">{tools2}</text>
  <text x="475" y="642" fill="#55657a" font-size="13" text-anchor="middle">{tools3}</text>

  <line x1="60" y1="532" x2="60" y2="700" stroke="#1d2733" stroke-width="2" marker-end="url(#b-fl)"/>
  <text x="22" y="684" fill="#1d2733" font-size="13" font-weight="600">CAT</text>
  <line x1="320" y1="402" x2="320" y2="700" stroke="#1d2733" stroke-width="2" marker-start="url(#b-fl)" marker-end="url(#b-fl)"/>
  <text x="327" y="686" fill="#1d2733" font-size="13" font-weight="600">{audio}</text>

  <rect x="20" y="702" width="380" height="100" rx="12" fill="#fff" stroke="#1d2733" stroke-width="2.5"/>
  <text x="210" y="738" fill="#1d2733" font-size="18" font-weight="700" text-anchor="middle">{rig}</text>
  <text x="210" y="762" fill="#55657a" font-size="14" text-anchor="middle">{rig_usb1}</text>
  <text x="210" y="782" fill="#55657a" font-size="14" text-anchor="middle">{rig_usb2}</text>
  <path d="M602,488 H628 V690 H520 V700" fill="none" stroke="#c8402f" stroke-width="2" marker-end="url(#b-flr)"/>
  <rect x="420" y="702" width="200" height="100" rx="12" fill="#fff" stroke="#c8402f" stroke-width="2"/>
  <text x="520" y="738" fill="#1d2733" font-size="17" font-weight="700" text-anchor="middle">{alerts}</text>
  <text x="520" y="762" fill="#55657a" font-size="13" text-anchor="middle">{al1}</text>
  <text x="520" y="782" fill="#55657a" font-size="13" text-anchor="middle">{al2}</text>
</svg>
"""

T = {
    "fr": dict(
        r_title="Où est quoi : les appareils, le réseau, la station",
        r_desc="En haut, hors de la maison : PC portable, tablette et smartphone joignent Internet par la 4G, la 5G ou un autre Wi-Fi, puis la box de la maison par un tunnel VPN chiffré (ou un port 443 ouvert). À la maison, sur le réseau local (câble ou Wi-Fi) : le PC de la station (Debian, Raspberry Pi ou Windows), relié au poste par un câble USB, et les mêmes appareils, qui ouvrent la même adresse https://<station>:8443.",
        away="AILLEURS : 4G / 5G, AUTRE WI-FI", laptop="PC portable", browser="navigateur", tablet="Tablette",
        browser_or_app="navigateur ou application", phone="Smartphone", app_auto="application, Android Auto",
        vpn_profile="un profil VPN par appareil, jamais partagé", mobile="réseau mobile 4G / 5G ou autre box",
        tunnel="tunnel VPN chiffré (recommandé)", tunnel_ex="WireGuard de la box, Tailscale…",
        port_note="ou port 443 ouvert sur la box (partie 5)", home="À LA MAISON : RÉSEAU LOCAL",
        box="Box Internet", box_sub="serveur VPN · adresse réservée à la station", cable_wifi="câble ou Wi-Fi",
        cable_advised="câble conseillé", station_pc="PC de la station", systems="Debian, Raspberry Pi ou Windows",
        page_audio="page et son : https://…:8443", station_parts="passerelle, superviseur, sécurités",
        detail_next="détail : schéma suivant", home_too="À LA MAISON AUSSI", pc_browser="PC · navigateur",
        phone_wifi="Smartphone en Wi-Fi", usb="câble USB", usb_sub="commande (CAT) + son", rig="Poste (TRX)",
        antenna="antenne, ou charge fictive", for_tests="pour les essais", same_address="Même adresse partout",
        home_and_vpn="à la maison et en VPN :",
        b_title="Les briques d'une station openRemoteTRX",
        b_desc="De haut en bas : l'utilisateur (navigateur ou application Android) joint par le réseau local ou le VPN la passerelle du PC de la station ; la passerelle commande le poste par rigctld (Hamlib) et échange le son avec sa carte son ; le superviseur surveille le tout, ne peut que couper l'émission (T 0) et envoie les alertes ntfy ; openRemoteTRX Console et les tableaux de bord lisent l'état ; station.toml porte la configuration ; le poste est relié par un câble USB.",
        user_side="CÔTÉ UTILISATEUR", browser_t="Navigateur", devices="PC, tablette, téléphone",
        android_app="Application Android", android_auto="+ Android Auto en voiture",
        net="Réseau local ou VPN (schéma précédent)", net_sub="HTTPS port 8443 (commandes) + WebRTC (son)",
        station_caps="PC DE LA STATION", gateway="Passerelle · trx-gateway",
        gw1="sert la page, vérifie les comptes, transporte le son, décide de",
        gw2="l'émission : PTT en bascule, TOT, bandes, retour en réception",
        commands="commandes", rig1="parle au poste ; écoute sur", rig2="cette machine seulement",
        supervisor="Superviseur", sup1="surveille tout, ne peut que", sup2="COUPER l'émission",
        watch="surveille, relance", config="la configuration", tools="Outils",
        tools1="openRemoteTRX Console, tableaux", tools2="de bord : lisent l'état ;", tools3="seule action : STOP TX",
        audio="son", rig_usb1="un seul câble USB sur la plupart des postes :",
        rig_usb2="commande (CAT) + carte son du poste", alerts="Alertes ntfy",
        al1="sur ton téléphone : coupure,", al2="panne, mise en sécurité"),
    "en": dict(
        r_title="What is where: devices, network, station",
        r_desc="At the top, away from home: laptop, tablet and smartphone reach the Internet over 4G, 5G or another Wi-Fi, then the home router through an encrypted VPN tunnel (or an open port 443). At home, on the local network (cable or Wi-Fi): the station PC (Debian, Raspberry Pi or Windows), connected to the transceiver by a USB cable, and the same devices, which open the same address https://<station>:8443.",
        away="AWAY: 4G / 5G, OTHER WI-FI", laptop="Laptop", browser="browser", tablet="Tablet",
        browser_or_app="browser or app", phone="Smartphone", app_auto="app, Android Auto",
        vpn_profile="one VPN profile per device, never shared", mobile="4G / 5G mobile network or another router",
        tunnel="encrypted VPN tunnel (recommended)", tunnel_ex="router WireGuard, Tailscale…",
        port_note="or port 443 open on the router (part 5)", home="AT HOME: LOCAL NETWORK",
        box="Internet router", box_sub="VPN server · address reserved for the station", cable_wifi="cable or Wi-Fi",
        cable_advised="cable recommended", station_pc="Station PC", systems="Debian, Raspberry Pi or Windows",
        page_audio="page and audio: https://…:8443", station_parts="gateway, supervisor, safety",
        detail_next="details: next diagram", home_too="AT HOME TOO", pc_browser="PC · browser",
        phone_wifi="Smartphone on Wi-Fi", usb="USB cable", usb_sub="control (CAT) + audio", rig="Transceiver (TRX)",
        antenna="antenna, or dummy load", for_tests="for the tests", same_address="Same address everywhere",
        home_and_vpn="at home and over the VPN:",
        b_title="The building blocks of an openRemoteTRX station",
        b_desc="From top to bottom: the user (browser or Android app) reaches the gateway of the station PC over the local network or the VPN; the gateway controls the transceiver through rigctld (Hamlib) and exchanges audio with its sound card; the supervisor watches everything, can only cut transmission (T 0) and sends ntfy alerts; openRemoteTRX Console and the dashboards read the status; station.toml holds the configuration; the transceiver is connected by a USB cable.",
        user_side="USER SIDE", browser_t="Browser", devices="PC, tablet, phone",
        android_app="Android app", android_auto="+ Android Auto in the car",
        net="Local network or VPN (previous diagram)", net_sub="HTTPS port 8443 (commands) + WebRTC (audio)",
        station_caps="STATION PC", gateway="Gateway · trx-gateway",
        gw1="serves the page, checks accounts, carries audio, decides on",
        gw2="transmission: toggle PTT, TOT, bands, back to receive",
        commands="commands", rig1="talks to the transceiver; listens", rig2="on this machine only",
        supervisor="Supervisor", sup1="watches everything, can only", sup2="CUT transmission",
        watch="watches, restarts", config="the configuration", tools="Tools",
        tools1="openRemoteTRX Console, dashboards:", tools2="read the status;", tools3="only action: STOP TX",
        audio="audio", rig_usb1="a single USB cable on most transceivers:",
        rig_usb2="control (CAT) + the rig's sound card", alerts="ntfy alerts",
        al1="on your phone: cut,", al2="fault, safety lockout"),
    "de": dict(
        r_title="Was ist wo: Geräte, Netzwerk, Station",
        r_desc="Oben, unterwegs: Laptop, Tablet und Smartphone erreichen das Internet über 4G, 5G oder ein anderes WLAN, dann den Router zu Hause über einen verschlüsselten VPN-Tunnel (oder einen offenen Port 443). Zu Hause im lokalen Netz (Kabel oder WLAN): der Stations-PC (Debian, Raspberry Pi oder Windows), per USB-Kabel mit dem Transceiver verbunden, und dieselben Geräte, die dieselbe Adresse https://<station>:8443 öffnen.",
        away="UNTERWEGS: 4G / 5G, ANDERES WLAN", laptop="Laptop", browser="Browser", tablet="Tablet",
        browser_or_app="Browser oder App", phone="Smartphone", app_auto="App, Android Auto",
        vpn_profile="ein VPN-Profil pro Gerät, nie geteilt", mobile="Mobilfunk 4G / 5G oder anderer Router",
        tunnel="verschlüsselter VPN-Tunnel (empfohlen)", tunnel_ex="WireGuard des Routers, Tailscale…",
        port_note="oder Port 443 am Router offen (Teil 5)", home="ZU HAUSE: LOKALES NETZ",
        box="Internet-Router", box_sub="VPN-Server · feste Adresse für die Station", cable_wifi="Kabel oder WLAN",
        cable_advised="Kabel empfohlen", station_pc="Stations-PC", systems="Debian, Raspberry Pi oder Windows",
        page_audio="Seite und Ton: https://…:8443", station_parts="Gateway, Supervisor, Sicherheit",
        detail_next="Details: nächstes Schema", home_too="AUCH ZU HAUSE", pc_browser="PC · Browser",
        phone_wifi="Smartphone im WLAN", usb="USB-Kabel", usb_sub="Steuerung (CAT) + Ton", rig="Transceiver (TRX)",
        antenna="Antenne oder Dummy-Load", for_tests="für die Tests", same_address="Überall dieselbe Adresse",
        home_and_vpn="zu Hause und über VPN:",
        b_title="Die Bausteine einer openRemoteTRX-Station",
        b_desc="Von oben nach unten: Der Benutzer (Browser oder Android-App) erreicht über das lokale Netz oder das VPN das Gateway des Stations-PCs; das Gateway steuert den Transceiver über rigctld (Hamlib) und tauscht den Ton mit seiner Soundkarte aus; der Supervisor überwacht alles, kann das Senden nur abschalten (T 0) und schickt ntfy-Warnungen; openRemoteTRX Console und die Dashboards lesen den Zustand; station.toml enthält die Konfiguration; der Transceiver ist per USB-Kabel verbunden.",
        user_side="BENUTZERSEITE", browser_t="Browser", devices="PC, Tablet, Telefon",
        android_app="Android-App", android_auto="+ Android Auto im Auto",
        net="Lokales Netz oder VPN (vorheriges Schema)", net_sub="HTTPS Port 8443 (Befehle) + WebRTC (Ton)",
        station_caps="STATIONS-PC", gateway="Gateway · trx-gateway",
        gw1="liefert die Seite, prüft Konten, überträgt den Ton, entscheidet",
        gw2="über das Senden: PTT als Umschalter, TOT, Bänder, zurück auf Empfang",
        commands="Befehle", rig1="spricht mit dem Transceiver;", rig2="nur auf diesem Rechner erreichbar",
        supervisor="Supervisor", sup1="überwacht alles, kann das", sup2="Senden nur ABSCHALTEN",
        watch="überwacht, startet neu", config="die Konfiguration", tools="Werkzeuge",
        tools1="openRemoteTRX Console, Dashboards:", tools2="lesen den Zustand;", tools3="einzige Aktion: STOP TX",
        audio="Ton", rig_usb1="bei den meisten Geräten ein einziges USB-Kabel:",
        rig_usb2="Steuerung (CAT) + Soundkarte des Geräts", alerts="ntfy-Warnungen",
        al1="auf Ihrem Telefon: Abschaltung,", al2="Störung, Sicherheitsabschaltung"),
    "es": dict(
        r_title="Qué está dónde: equipos, red, estación",
        r_desc="Arriba, fuera de casa: portátil, tableta y smartphone llegan a Internet por 4G, 5G u otra Wi-Fi, y luego al router de casa por un túnel VPN cifrado (o un puerto 443 abierto). En casa, en la red local (cable o Wi-Fi): el PC de la estación (Debian, Raspberry Pi o Windows), unido al transceptor por un cable USB, y los mismos equipos, que abren la misma dirección https://<station>:8443.",
        away="FUERA: 4G / 5G, OTRA WI-FI", laptop="Portátil", browser="navegador", tablet="Tableta",
        browser_or_app="navegador o aplicación", phone="Smartphone", app_auto="aplicación, Android Auto",
        vpn_profile="un perfil VPN por equipo, nunca compartido", mobile="red móvil 4G / 5G u otro router",
        tunnel="túnel VPN cifrado (recomendado)", tunnel_ex="WireGuard del router, Tailscale…",
        port_note="o puerto 443 abierto en el router (parte 5)", home="EN CASA: RED LOCAL",
        box="Router de Internet", box_sub="servidor VPN · dirección reservada a la estación", cable_wifi="cable o Wi-Fi",
        cable_advised="cable recomendado", station_pc="PC de la estación", systems="Debian, Raspberry Pi o Windows",
        page_audio="página y audio: https://…:8443", station_parts="pasarela, supervisor, seguridad",
        detail_next="detalle: esquema siguiente", home_too="TAMBIÉN EN CASA", pc_browser="PC · navegador",
        phone_wifi="Smartphone en Wi-Fi", usb="cable USB", usb_sub="control (CAT) + audio", rig="Transceptor (TRX)",
        antenna="antena, o carga ficticia", for_tests="para las pruebas", same_address="La misma dirección siempre",
        home_and_vpn="en casa y por VPN:",
        b_title="Los bloques de una estación openRemoteTRX",
        b_desc="De arriba abajo: el usuario (navegador o aplicación Android) llega por la red local o la VPN a la pasarela del PC de la estación; la pasarela controla el transceptor mediante rigctld (Hamlib) e intercambia el audio con su tarjeta de sonido; el supervisor lo vigila todo, solo puede cortar la transmisión (T 0) y envía las alertas ntfy; openRemoteTRX Console y los paneles leen el estado; station.toml contiene la configuración; el transceptor se conecta por un cable USB.",
        user_side="LADO DEL USUARIO", browser_t="Navegador", devices="PC, tableta, teléfono",
        android_app="Aplicación Android", android_auto="+ Android Auto en el coche",
        net="Red local o VPN (esquema anterior)", net_sub="HTTPS puerto 8443 (órdenes) + WebRTC (audio)",
        station_caps="PC DE LA ESTACIÓN", gateway="Pasarela · trx-gateway",
        gw1="sirve la página, comprueba las cuentas, lleva el audio, decide",
        gw2="la transmisión: PTT alterno, TOT, bandas, vuelta a recepción",
        commands="órdenes", rig1="habla con el transceptor; solo", rig2="escucha en esta máquina",
        supervisor="Supervisor", sup1="lo vigila todo, solo puede", sup2="CORTAR la transmisión",
        watch="vigila, reinicia", config="la configuración", tools="Herramientas",
        tools1="openRemoteTRX Console, paneles:", tools2="leen el estado;", tools3="única acción: STOP TX",
        audio="audio", rig_usb1="un solo cable USB en la mayoría de equipos:",
        rig_usb2="control (CAT) + tarjeta de sonido del equipo", alerts="Alertas ntfy",
        al1="en tu teléfono: corte,", al2="avería, bloqueo de seguridad"),
}

def build() -> dict[Path, bytes]:
    """{fichier: contenu} des schémas de chaque langue."""
    out: dict[Path, bytes] = {}
    for lang, words in T.items():
        values = {k: escape(v, quote=False) for k, v in words.items()}
        values["font"] = FONT
        folder = ROOT / lang / "images"
        out[folder / "reseau.svg"] = RESEAU.format(**values).encode("utf-8")
        out[folder / "briques.svg"] = BRIQUES.format(**values).encode("utf-8")
    return out


def main() -> int:
    for path, data in build().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"Écrit : {path.relative_to(ROOT.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
