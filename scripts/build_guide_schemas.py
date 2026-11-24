# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Schémas de la partie 0 du guide de l'opérateur, en thème clair, dans les quatre langues :
User-Guide/<langue>/images/reseau.svg (appareils, 4G / 5G, box et VPN, réseau local, station, poste), briques.svg
(l'intérieur du PC de la station, sur fond ambre) et, pour la partie 4, applis.svg (les trois pages ouvertes dans le
navigateur, chacune sur son port). Un seul dessin, les textes de chaque langue dans T : un changement
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

APPLIS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 672" width="760" height="672" role="img" aria-labelledby="a-titre a-desc" font-family="{font}">
  <title id="a-titre">{a_title}</title>
  <desc id="a-desc">{a_desc}</desc>
  <defs>
    <marker id="a-m8443" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f74c0"/></marker><marker id="a-m8444" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0b8f84"/></marker><marker id="a-m8450" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#b07a12"/></marker>
    <clipPath id="a-c1"><rect x="20" y="78" width="330" height="200" rx="8"/></clipPath>
    <clipPath id="a-c2"><rect x="20" y="338" width="330" height="200" rx="8"/></clipPath>
    <clipPath id="a-c3"><rect x="20" y="598" width="330" height="200" rx="8"/></clipPath>
  </defs>
  <rect width="760" height="672" rx="14" fill="#ffffff"/>
  <text x="20" y="34" fill="#2c5d8f" font-size="14" font-weight="700" letter-spacing=".6">{a_head}</text>
  <text x="20" y="56" fill="#55657a" font-size="13">{a_sub}</text>
  <g transform="translate(20,80) scale(0.84) translate(-20,-78)">
  <g clip-path="url(#a-c1)">
    <rect x="20" y="78" width="330" height="200" fill="#04070b"/>
    <rect x="20" y="78" width="330" height="26" fill="#dfe5ec"/>
    <circle cx="34" cy="91" r="4" fill="#e0524a"/><circle cx="46" cy="91" r="4" fill="#f5b83d"/><circle cx="58" cy="91" r="4" fill="#3fae72"/>
    <rect x="72" y="84" width="268" height="14" rx="7" fill="#fff"/>
    <text x="80" y="95" fill="#1d2733" font-size="10">https://&lt;station&gt;:8443</text>
    <rect x="20" y="104" width="330" height="20" fill="#0a1119"/>
    <text x="30" y="118" fill="#7f90a5" font-size="9">openRemoteTRX</text>
    <rect x="290" y="109" width="50" height="11" rx="5" fill="#3fae72"/>
    <text x="315" y="118" fill="#fff" font-size="8" text-anchor="middle">RX</text>
    <text x="30" y="148" fill="#e9f1fb" font-size="22" font-weight="700" font-family="ui-monospace,Consolas,monospace">14.074.000</text>
    <rect x="186" y="134" width="34" height="15" rx="7" fill="#2f86e0"/>
    <text x="203" y="145" fill="#fff" font-size="9" text-anchor="middle">USB</text>
    <text x="30" y="166" fill="#7f90a5" font-size="8">S</text>
    <rect x="40" y="160" width="180" height="7" rx="3" fill="#0f151d"/>
    <rect x="40" y="160" width="112" height="7" rx="3" fill="#7cc0ff"/>
    <!-- spectre -->
    <rect x="30" y="176" width="310" height="54" fill="#0b1118"/>
    <polyline points="30,222 50,220 70,218 90,214 100,200 106,190 112,206 130,216 160,212 175,196 180,182 186,200 200,214 230,216 250,210 258,198 264,210 290,218 320,219 340,221" fill="none" stroke="#7cc0ff" stroke-width="1.5"/>
    <rect x="30" y="230" width="310" height="10" fill="#10324f"/>
    <rect x="100" y="230" width="8" height="10" fill="#f5b83d"/><rect x="176" y="230" width="8" height="10" fill="#e0524a"/>
    <!-- PTT et STOP -->
    <rect x="30" y="248" width="196" height="24" rx="12" fill="#0f151d" stroke="#2f86e0"/>
    <text x="128" y="264" fill="#e9f1fb" font-size="11" font-weight="700" text-anchor="middle">PTT</text>
    <rect x="236" y="248" width="104" height="24" rx="12" fill="#c8402f"/>
    <text x="288" y="264" fill="#fff" font-size="11" font-weight="700" text-anchor="middle">STOP</text>
  </g>
  <rect x="20" y="78" width="330" height="200" rx="8" fill="none" stroke="#2f74c0" stroke-width="2"/>
  </g>
  <text x="312" y="99" fill="#1d2733" font-size="18" font-weight="700">{a_web}</text>
  <text x="312" y="118" fill="#2f74c0" font-size="14" font-weight="600">https://&lt;station&gt;:8443</text>
  <text x="312" y="142" fill="#1d2733" font-size="14">{a_web1}</text>
  <text x="312" y="157" fill="#1d2733" font-size="14">{a_web2}</text>
  <text x="312" y="181" fill="#55657a" font-size="13">{a_web3}</text>
  <text x="312" y="197" fill="#55657a" font-size="13">{a_web4}</text>
  <text x="312" y="221" fill="#c8402f" font-size="13" font-weight="600">{a_web5}</text>
  <g transform="translate(20,280) scale(0.84) translate(-20,-338)">
  <g clip-path="url(#a-c2)">
    <rect x="20" y="338" width="330" height="200" fill="#eef2f4"/>
    <rect x="20" y="338" width="330" height="26" fill="#dfe5ec"/>
    <circle cx="34" cy="351" r="4" fill="#e0524a"/><circle cx="46" cy="351" r="4" fill="#f5b83d"/><circle cx="58" cy="351" r="4" fill="#3fae72"/>
    <rect x="72" y="344" width="268" height="14" rx="7" fill="#fff"/>
    <text x="80" y="355" fill="#1d2733" font-size="10">https://&lt;station&gt;:8444</text>
    <rect x="20" y="364" width="330" height="22" fill="#ffffff" stroke="#d5dee4"/>
    <circle cx="32" cy="375" r="4" fill="#0b8f84"/>
    <text x="40" y="379" fill="#14202a" font-size="9" font-weight="600">{a_running}</text>
    <rect x="210" y="369" width="36" height="12" rx="6" fill="#0b8f84"/><text x="228" y="378" fill="#fff" font-size="7" text-anchor="middle">Basic</text>
    <rect x="249" y="369" width="40" height="12" rx="6" fill="#fff" stroke="#d5dee4"/><text x="269" y="378" fill="#5a6b78" font-size="7" text-anchor="middle">Normal</text>
    <rect x="292" y="369" width="40" height="12" rx="6" fill="#fff" stroke="#d5dee4"/><text x="312" y="378" fill="#5a6b78" font-size="7" text-anchor="middle">Expert</text>
    <rect x="30" y="392" width="310" height="14" rx="7" fill="#fff" stroke="#d5dee4"/>
    <text x="40" y="402" fill="#5a6b78" font-size="8">{a_search}</text>
    <!-- tuiles des thèmes -->
    <g font-size="9" fill="#14202a">
      <rect x="30" y="412" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="38" y="426" font-weight="700">{a_t1}</text><text x="38" y="439" fill="#5a6b78" font-size="7">{a_t1d}</text>
      <rect x="136" y="412" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="144" y="426" font-weight="700">{a_t2}</text><text x="144" y="439" fill="#5a6b78" font-size="7">{a_t2d}</text>
      <rect x="242" y="412" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="250" y="426" font-weight="700">{a_t3}</text><text x="250" y="439" fill="#5a6b78" font-size="7">{a_t3d}</text>
      <rect x="30" y="452" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="38" y="466" font-weight="700">{a_t4}</text><text x="38" y="479" fill="#5a6b78" font-size="7">{a_t4d}</text>
      <rect x="136" y="452" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="144" y="466" font-weight="700">{a_t6}</text><text x="144" y="479" fill="#5a6b78" font-size="7">{a_t6d}</text>
      <rect x="242" y="452" width="98" height="34" rx="6" fill="#fff" stroke="#d5dee4"/><text x="250" y="466" font-weight="700">{a_t7}</text><text x="250" y="479" fill="#5a6b78" font-size="7">{a_t7d}</text>
    </g>
    <!-- terminal -->
    <rect x="30" y="494" width="310" height="38" rx="5" fill="#0b1115"/>
    <text x="38" y="508" fill="#53f3d8" font-size="8" font-family="ui-monospace,Consolas,monospace">{a_ok}</text>
    <text x="38" y="521" fill="#c47a00" font-size="8" font-family="ui-monospace,Consolas,monospace">{a_warn}</text>
  </g>
  <rect x="20" y="338" width="330" height="200" rx="8" fill="none" stroke="#0b8f84" stroke-width="2"/>
  </g>
  <text x="312" y="299" fill="#1d2733" font-size="18" font-weight="700">openRemoteTRX Console</text>
  <text x="312" y="318" fill="#0b8f84" font-size="14" font-weight="600">https://&lt;station&gt;:8444</text>
  <text x="312" y="342" fill="#1d2733" font-size="14">{a_con1}</text>
  <text x="312" y="357" fill="#1d2733" font-size="14">{a_con2}</text>
  <text x="312" y="381" fill="#55657a" font-size="13">{a_con3}</text>
  <text x="312" y="397" fill="#55657a" font-size="13">{a_con4}</text>
  <text x="312" y="421" fill="#55657a" font-size="13">{a_con5}</text>
  <g transform="translate(20,480) scale(0.84) translate(-20,-598)">
  <g clip-path="url(#a-c3)">
    <rect x="20" y="598" width="330" height="200" fill="#0B0F14"/>
    <rect x="20" y="598" width="330" height="26" fill="#dfe5ec"/>
    <circle cx="34" cy="611" r="4" fill="#e0524a"/><circle cx="46" cy="611" r="4" fill="#f5b83d"/><circle cx="58" cy="611" r="4" fill="#3fae72"/>
    <rect x="72" y="604" width="268" height="14" rx="7" fill="#fff"/>
    <text x="80" y="615" fill="#1d2733" font-size="10">https://&lt;station&gt;:8450</text>
    <text x="30" y="642" fill="#E6EDF3" font-size="10" font-weight="700">IC-7300MK2</text>
    <text x="340" y="642" fill="#8B9BAD" font-size="10" text-anchor="end" font-family="ui-monospace,Consolas,monospace">18:42</text>
    <!-- carte poste -->
    <rect x="30" y="650" width="150" height="62" rx="6" fill="#131A22" stroke="#233040"/>
    <text x="40" y="666" fill="#8B9BAD" font-size="8">{a_rig}</text>
    <text x="40" y="686" fill="#4FC3F7" font-size="15" font-weight="700" font-family="ui-monospace,Consolas,monospace">RX</text>
    <text x="70" y="686" fill="#E6EDF3" font-size="10">14.074 USB</text>
    <text x="40" y="703" fill="#8B9BAD" font-size="8">{a_tot}</text>
    <!-- carte machine -->
    <rect x="190" y="650" width="150" height="62" rx="6" fill="#131A22" stroke="#233040"/>
    <text x="200" y="666" fill="#8B9BAD" font-size="8">{a_machine}</text>
    <text x="200" y="684" fill="#E6EDF3" font-size="10">54 °C · 18 %</text>
    <polyline points="200,704 215,700 230,702 245,696 260,699 275,690 290,694 305,698 330,695" fill="none" stroke="#4ADE80" stroke-width="1.5"/>
    <!-- pastilles des comptes -->
    <rect x="30" y="720" width="310" height="34" rx="6" fill="#131A22" stroke="#233040"/>
    <text x="40" y="734" fill="#8B9BAD" font-size="8">{a_conn}</text>
    <circle cx="44" cy="745" r="4" fill="#4ADE80"/><text x="52" y="748" fill="#E6EDF3" font-size="8">PC</text>
    <circle cx="80" cy="745" r="4" fill="#4ADE80"/><text x="88" y="748" fill="#E6EDF3" font-size="8">S25</text>
    <circle cx="120" cy="745" r="4" fill="#5E6B79"/><text x="128" y="748" fill="#8B9BAD" font-size="8">{a_tablet}</text>
    <!-- alertes -->
    <rect x="30" y="760" width="310" height="30" rx="6" fill="#131A22" stroke="#233040"/>
    <circle cx="44" cy="775" r="4" fill="#4ADE80"/><text x="52" y="778" fill="#E6EDF3" font-size="8">{a_inet}</text>
    <circle cx="130" cy="775" r="4" fill="#F5B83D"/><text x="138" y="778" fill="#E6EDF3" font-size="8">{a_alert}</text>
  </g>
  <rect x="20" y="598" width="330" height="200" rx="8" fill="none" stroke="#d99a2b" stroke-width="2"/>
  </g>
  <text x="312" y="499" fill="#1d2733" font-size="18" font-weight="700">{a_dash}</text>
  <text x="312" y="516" fill="#1d2733" font-size="15" font-weight="700">{a_dash2}</text>
  <text x="312" y="535" fill="#8a5a0a" font-size="14" font-weight="600">https://&lt;station&gt;:8450</text>
  <text x="312" y="559" fill="#1d2733" font-size="14">{a_das1}</text>
  <text x="312" y="575" fill="#1d2733" font-size="14">{a_das2}</text>
  <text x="312" y="599" fill="#55657a" font-size="13">{a_das3}</text>
  <text x="312" y="614" fill="#55657a" font-size="13">{a_das4}</text>
  <text x="312" y="630" fill="#55657a" font-size="13">{a_das5}</text>
  <rect x="596" y="20" width="148" height="632" rx="14" fill="#fff1d6" stroke="#d99a2b" stroke-width="2.5"/>
  <text x="670" y="50" fill="#1d2733" font-size="16" font-weight="700" text-anchor="middle">{station_pc}</text>
  <text x="670" y="70" fill="#55657a" font-size="12" text-anchor="middle">{a_one}</text>
  <line x1="500" y1="113" x2="606" y2="113" stroke="#2f74c0" stroke-width="2.5" marker-end="url(#a-m8443)"/>
  <rect x="610" y="96" width="120" height="34" rx="8" fill="#fff" stroke="#2f74c0" stroke-width="2"/>
  <text x="670" y="118" fill="#2f74c0" font-size="15" font-weight="700" text-anchor="middle">port 8443</text>
  <line x1="500" y1="313" x2="606" y2="313" stroke="#0b8f84" stroke-width="2.5" marker-end="url(#a-m8444)"/>
  <rect x="610" y="296" width="120" height="34" rx="8" fill="#fff" stroke="#0b8f84" stroke-width="2"/>
  <text x="670" y="318" fill="#0b8f84" font-size="15" font-weight="700" text-anchor="middle">port 8444</text>
  <line x1="500" y1="530" x2="606" y2="530" stroke="#b07a12" stroke-width="2.5" marker-end="url(#a-m8450)"/>
  <rect x="610" y="513" width="120" height="34" rx="8" fill="#fff" stroke="#b07a12" stroke-width="2"/>
  <text x="670" y="535" fill="#b07a12" font-size="15" font-weight="700" text-anchor="middle">port 8450</text>
  <text x="670" y="612" fill="#55657a" font-size="12" text-anchor="middle">{a_three1}</text>
  <text x="670" y="630" fill="#55657a" font-size="12" text-anchor="middle">{a_three2}</text>
</svg>
"""

# Schéma des trois pages ouvertes dans le navigateur (partie 4), textes propres à ce schéma.
TA = {
    "fr": dict(
        a_title="Trois pages de la station dans le navigateur",
        a_desc="Trois pages séparées, chacune reliée directement à son propre port du PC de la station, à la même adresse : l'application Web (https://<station>:8443) pour piloter le poste, la seule qui peut émettre ; openRemoteTRX Console (https://<station>:8444) pour configurer et dépanner, comptes administrateurs seulement ; le tableau de bord des signes vitaux (https://<station>:8450), en lecture seule, sur Debian et Raspberry Pi.",
        a_head="DANS TON NAVIGATEUR : PC, TABLETTE, TÉLÉPHONE",
        a_sub="trois pages séparées : chacune s'ouvre seule, sur son propre port de la station",
        a_web="Application Web", a_web1="piloter le poste : fréquence,", a_web2="mode, son reçu, émission",
        a_web3="comptes opérateurs et visiteurs", a_web4="(ou l'application Android)", a_web5="la seule qui peut émettre",
        a_con1="configurer, démarrer, essayer,", a_con2="mettre à jour, dépanner",
        a_con3="comptes administrateurs seulement", a_con4="(à ouvrir au menu 4.6)", a_con5="jamais depuis Internet",
        a_dash="Tableau de bord", a_dash2="des signes vitaux", a_das1="surveiller d'un coup d'œil :",
        a_das2="poste, machine, connexions", a_das3="lecture seule, sans mot de passe", a_das4="petit écran près du poste",
        a_das5="Debian et Raspberry Pi", a_one="une seule adresse", a_three1="trois pages", a_three2="indépendantes",
        a_running="Station en marche", a_search="Rechercher un menu…",
        a_t1="1 Station", a_t1d="démarrer, arrêter", a_t2="2 Poste", a_t2d="assistant, essai",
        a_t3="3 Sécurité", a_t3d="bandes, TOT", a_t4="4 Accès", a_t4d="comptes, appairage",
        a_t6="6 Dépannage", a_t6d="diagnostic, rapport", a_t7="7 Mises à jour", a_t7d="nouvelle version",
        a_ok="[OK] rigctld répond", a_warn="[ATTENTION] mise à jour disponible",
        a_rig="POSTE", a_machine="MACHINE", a_conn="CONNEXIONS", a_tablet="tablette", a_inet="Internet OK",
        a_alert="1 alerte depuis 24 h", a_tot="TOT 90 s · bandes OK"),
    "en": dict(
        a_title="Three station pages in the browser",
        a_desc="Three separate pages, each connected directly to its own port of the station PC, at the same address: the Web app (https://<station>:8443) to control the transceiver, the only one that can transmit; openRemoteTRX Console (https://<station>:8444) to configure and troubleshoot, administrator accounts only; the vital signs dashboard (https://<station>:8450), read-only, on Debian and Raspberry Pi.",
        a_head="IN YOUR BROWSER: PC, TABLET, PHONE",
        a_sub="three separate pages: each opens on its own, on its own port of the station",
        a_web="Web app", a_web1="control the transceiver: frequency,", a_web2="mode, received audio, transmit",
        a_web3="operator and visitor accounts", a_web4="(or the Android app)", a_web5="the only one that can transmit",
        a_con1="configure, start, test,", a_con2="update, troubleshoot",
        a_con3="administrator accounts only", a_con4="(enable in menu 4.6)", a_con5="never from the Internet",
        a_dash="Vital signs", a_dash2="dashboard", a_das1="monitor at a glance:",
        a_das2="transceiver, computer, connections", a_das3="read-only, no password", a_das4="small screen next to the rig",
        a_das5="Debian and Raspberry Pi", a_one="one single address", a_three1="three independent", a_three2="pages",
        a_running="Station running", a_search="Search a menu…",
        a_t1="1 Station", a_t1d="start, stop", a_t2="2 Transceiver", a_t2d="wizard, test",
        a_t3="3 Safety", a_t3d="bands, TOT", a_t4="4 Access", a_t4d="accounts, pairing",
        a_t6="6 Troubleshooting", a_t6d="diagnostics, report", a_t7="7 Updates", a_t7d="new version",
        a_ok="[OK] rigctld answers", a_warn="[WARNING] update available",
        a_rig="TRANSCEIVER", a_machine="COMPUTER", a_conn="CONNECTIONS", a_tablet="tablet", a_inet="Internet OK",
        a_alert="1 alert in the last 24 h", a_tot="TOT 90 s · bands OK"),
    "de": dict(
        a_title="Drei Seiten der Station im Browser",
        a_desc="Drei getrennte Seiten, jede direkt mit ihrem eigenen Port des Stations-PCs verbunden, unter derselben Adresse: die Web-App (https://<station>:8443) zum Steuern des Transceivers, die einzige, die senden kann; openRemoteTRX Console (https://<station>:8444) zum Einrichten und zur Fehlersuche, nur für Administratorkonten; das Dashboard der Vitalwerte (https://<station>:8450), nur lesend, unter Debian und Raspberry Pi.",
        a_head="IN IHREM BROWSER: PC, TABLET, TELEFON",
        a_sub="drei getrennte Seiten: jede öffnet sich allein, auf ihrem eigenen Port der Station",
        a_web="Web-App", a_web1="Transceiver steuern: Frequenz,", a_web2="Betriebsart, Empfang, Senden",
        a_web3="Operator- und Besucherkonten", a_web4="(oder die Android-App)", a_web5="die einzige, die senden kann",
        a_con1="einrichten, starten, testen,", a_con2="aktualisieren, Fehler suchen",
        a_con3="nur Administratorkonten", a_con4="(in Menü 4.6 freigeben)", a_con5="nie aus dem Internet",
        a_dash="Dashboard", a_dash2="der Vitalwerte", a_das1="auf einen Blick überwachen:",
        a_das2="Transceiver, Rechner, Verbindungen", a_das3="nur lesend, ohne Passwort", a_das4="kleiner Bildschirm am Gerät",
        a_das5="Debian und Raspberry Pi", a_one="eine einzige Adresse", a_three1="drei getrennte", a_three2="Seiten",
        a_running="Station läuft", a_search="Menü suchen…",
        a_t1="1 Station", a_t1d="starten, stoppen", a_t2="2 Transceiver", a_t2d="Assistent, Test",
        a_t3="3 Sicherheit", a_t3d="Bänder, TOT", a_t4="4 Zugang", a_t4d="Konten, Kopplung",
        a_t6="6 Fehlersuche", a_t6d="Diagnose, Bericht", a_t7="7 Updates", a_t7d="neue Version",
        a_ok="[OK] rigctld antwortet", a_warn="[ACHTUNG] Update verfügbar",
        a_rig="TRANSCEIVER", a_machine="RECHNER", a_conn="VERBINDUNGEN", a_tablet="Tablet", a_inet="Internet OK",
        a_alert="1 Alarm in 24 h", a_tot="TOT 90 s · Bänder OK"),
    "es": dict(
        a_title="Tres páginas de la estación en el navegador",
        a_desc="Tres páginas separadas, cada una conectada directamente a su propio puerto del PC de la estación, en la misma dirección: la aplicación Web (https://<station>:8443) para manejar el transceptor, la única que puede transmitir; openRemoteTRX Console (https://<station>:8444) para configurar y diagnosticar, solo cuentas de administrador; el panel de constantes vitales (https://<station>:8450), solo lectura, en Debian y Raspberry Pi.",
        a_head="EN TU NAVEGADOR: PC, TABLETA, TELÉFONO",
        a_sub="tres páginas separadas: cada una se abre sola, en su propio puerto de la estación",
        a_web="Aplicación Web", a_web1="manejar el transceptor: frecuencia,", a_web2="modo, audio recibido, emisión",
        a_web3="cuentas de operador y visitante", a_web4="(o la aplicación Android)", a_web5="la única que puede transmitir",
        a_con1="configurar, arrancar, probar,", a_con2="actualizar, diagnosticar",
        a_con3="solo cuentas de administrador", a_con4="(activar en el menú 4.6)", a_con5="nunca desde Internet",
        a_dash="Panel de", a_dash2="constantes vitales", a_das1="vigilar de un vistazo:",
        a_das2="transceptor, equipo, conexiones", a_das3="solo lectura, sin contraseña", a_das4="pantalla pequeña junto al equipo",
        a_das5="Debian y Raspberry Pi", a_one="una sola dirección", a_three1="tres páginas", a_three2="independientes",
        a_running="Estación en marcha", a_search="Buscar un menú…",
        a_t1="1 Estación", a_t1d="arrancar, parar", a_t2="2 Transceptor", a_t2d="asistente, prueba",
        a_t3="3 Seguridad", a_t3d="bandas, TOT", a_t4="4 Acceso", a_t4d="cuentas, emparejar",
        a_t6="6 Diagnóstico", a_t6d="diagnóstico, informe", a_t7="7 Actualizar", a_t7d="nueva versión",
        a_ok="[OK] rigctld responde", a_warn="[ATENCIÓN] actualización disponible",
        a_rig="TRANSCEPTOR", a_machine="EQUIPO", a_conn="CONEXIONES", a_tablet="tableta", a_inet="Internet OK",
        a_alert="1 alerta en 24 h", a_tot="TOT 90 s · bandas OK"),
}


def build() -> dict[Path, bytes]:
    """{fichier: contenu} des schémas de chaque langue."""
    out: dict[Path, bytes] = {}
    for lang, words in T.items():
        values = {k: escape(v, quote=False) for k, v in {**words, **TA[lang]}.items()}
        values["font"] = FONT
        folder = ROOT / lang / "images"
        out[folder / "reseau.svg"] = RESEAU.format(**values).encode("utf-8")
        out[folder / "briques.svg"] = BRIQUES.format(**values).encode("utf-8")
        out[folder / "applis.svg"] = APPLIS.format(**values).encode("utf-8")
    return out


def main() -> int:
    for path, data in build().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"Écrit : {path.relative_to(ROOT.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
