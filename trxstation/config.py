# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Chargement, validation et écriture de station.toml (stdlib uniquement).

Principe de conception : en cas de doute, on refuse d'émettre.
  - une liste de bandes vide signifie « émission interdite » ;
  - toute incohérence entre les temporisations de sécurité est une erreur bloquante.
"""
from __future__ import annotations

import ipaddress
import math
import json
import re
import tomllib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from .i18n import tool_translator
from .passwords import is_valid_hash
from .paths import default_state_dir, default_status_path


def _t(_key: str, **fields) -> str:
    """Message montré à l'opérateur (problème bloquant, avertissement), dans la langue de l'outil (lot L3) :
    catalogues `trxstation/i18n/checks.<langue>.json`, le français en référence. Lu À CHAQUE APPEL (jamais au
    chargement du module). Les noms de réglages ([safety] tot_s…) restent tels quels dans toutes les langues."""
    return tool_translator("checks")(_key, **fields)       # `_key` : un champ du texte peut s'appeler `key`


SCHEMA_VERSION = 1
DUMMY_MODEL = 1  # modèle factice Hamlib : simule un poste, sans matériel
PTT_TYPES = ("RIG", "RTS", "DTR", "GPIO", "GPION", "NONE")  # noms Hamlib (RIG = via CAT)


class ConfigError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass
class Rig:
    model: int = 0                 # numéro Hamlib (rigctl -l)
    port: str = ""                 # ex. /dev/serial/by-id/usb-...  (vide pour le modèle factice)
    speed: int | None = None       # débit série ; None = défaut Hamlib du modèle
    ptt_type: str = "RIG"          # RIG (CAT), RTS, DTR, GPIO, GPION, NONE
    ptt_port: str = ""             # périphérique PTT si différent du port CAT
    extra_conf: list[str] = field(default_factory=list)  # options -C de rigctld
    tx_modes: list[str] = field(default_factory=list)    # modes où l'émission est permise (vide = aucune restriction)
    max_power_w: int = 0                                 # puissance maximale du poste en watts ; 0 = inconnue (la page affiche des %)
    tuner: bool = False                                  # coupleur d'antenne du poste utilisé : réglages d'accord vérifiés à chaque connexion

    def rigctld_args(self, host: str, tcp_port: int) -> list[str]:
        args = ["rigctld", "-m", str(self.model), "-T", host, "-t", str(tcp_port)]
        if self.port:
            args += ["-r", self.port]
        if self.speed:
            args += ["-s", str(self.speed)]
        if self.ptt_type != "RIG":
            args += ["-P", self.ptt_type]
        if self.ptt_port:
            args += ["-p", self.ptt_port]
        for conf in self.extra_conf:
            args += ["-C", conf]
        return args + ["-C", NO_CACHE_CONF]          # EN DERNIER : Hamlib garde la dernière valeur d'une option


@dataclass
class Audio:
    capture_device: str = ""       # audio reçu du TRX (ex. plughw:CARD=CODEC,DEV=0)
    playback_device: str = ""      # audio injecté vers le TRX
    sample_rate: int = 48000       # seul 48000 est géré (Opus)
    rx_gain_db: float = 0.0        # gain appliqué au son reçu
    tx_gain_db: float = 0.0        # gain appliqué au son émis (prudence : un excès sature l'émetteur)


ROLES = ("operator", "listener")     # listener = visiteur en réception seule (docs/visiteurs-cahier-des-charges.md)
PSEUDO_MAX = 32


@dataclass
class ClientAuth:
    id: str = ""                   # identifiant de connexion (ex. phone, car)
    token: str = ""                # ANCIEN secret en clair (16 caractères au moins) : accepté, mais à remplacer
    password_hash: str = ""        # empreinte scrypt du mot de passe (trx-setup --add-client / --set-password)
    role: str = "operator"         # operator | listener (visiteur : écoute et affichage seulement) ; absent = operator
    pseudo: str = ""               # nom montré aux autres connectés (jamais l'identifiant) ; plusieurs comptes peuvent le partager
    enabled: bool = True           # false : connexion refusée, connexion en cours fermée
    expires: str = ""              # AAAA-MM-JJ : refusé après ce jour (heure locale de la station) ; vide = jamais
    admin: bool = False            # true : peut aussi ouvrir TRX Console sur le réseau ([remote_console], menu 4.6)

    def __post_init__(self) -> None:
        if isinstance(self.expires, date):      # date TOML écrite sans guillemets : expires = 2026-12-31
            self.expires = self.expires.isoformat()

    def expired(self, today: date) -> bool:
        if not self.expires:
            return False
        try:
            return today > date.fromisoformat(self.expires)
        except (TypeError, ValueError):
            return True                         # illisible (refusé par la validation) : refusé, par prudence


@dataclass
class Access:
    """Visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md). Relu par la passerelle sans redémarrer."""
    max_listeners: int = 0              # visiteurs connectés en même temps ; 0 = fonction désactivée
    max_operators: int = 4              # connexions opérateur : quota à part, jamais pris par un visiteur
    listeners_need_operator: bool = True   # true : visiteurs admis SEULEMENT si un opérateur est connecté à distance
    operator_grace_s: int = 60          # après la perte du dernier opérateur : attente avant de déconnecter les visiteurs
    listeners_outside_bands: bool = False  # false : silence pour les visiteurs quand la réception sort des [[bands]]
    listener_spectrum_fps: int = 5      # spectre HF des visiteurs : images par seconde au plus (l'opérateur garde max_fps)
    # Surcharge (gateway/api/overload.py) : au-delà pendant 10 s, visiteurs déconnectés ; retour sous les seuils 5 min
    overload_temp_c: int = 70           # température du processeur (°C) ; 70 : décision de l'utilisateur (2026-11-11)
    overload_cpu_pct: int = 90          # charge de tous les cœurs (%)
    overload_lag_ms: int = 100          # retard de la boucle de la passerelle (ms)
    overload_mem_pct: int = 10          # mémoire libre minimale (%)


@dataclass
class Swr:
    """Mesure de TOS (docs/tos-cahier-des-charges.md) : réglages de la STATION seulement (jamais depuis un client)."""
    enabled: bool = True                # false : mesure absente (fonction « swr » non annoncée)
    max_power_pct: int = 50             # plafond de puissance en % de la puissance du poste (jamais au-dessus de 50)
    max_points: int = 50                # points d'une mesure au plus
    point_tx_max_s: float = 2.0         # émission d'un point au plus (plafond de l'étalonnage du temps de lecture)


@dataclass
class Netprobe:
    """Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md) : mesure et affiche, n'agit JAMAIS sur l'émission.
    Seuils de l'indicateur = valeurs de DÉPART ; ceux choisis par l'opérateur (state_dir/netprobe/seuils.json) priment."""
    enabled: bool = True                # false : aucune mesure (fonction « netprobe » non annoncée)
    heartbeat_interval_s: float = 1.0   # période du battement réseau (0.5 à 10 s)
    outage_missed_beats: int = 3        # battements sans écho pour déclarer une coupure (2 à 20)
    lan_target: str = "auto"            # box à sonder (auto = passerelle par défaut) : sondes de la station
    internet_target: str = "1.1.1.1"    # cible Internet des sondes ; "" = aucune
    loss_warn_pct: float = 2.0          # perte sur 60 s : palier orange
    loss_alert_pct: float = 5.0         # palier rouge (5 % : décision de l'utilisateur, 2026-11-11)
    rtt_warn_ms: int = 250              # aller-retour p95 sur 60 s : palier orange
    rtt_alert_ms: int = 600             # palier rouge
    alert_outage_s: int = 10            # coupure plus longue : alerte ntfy (0 = aucune)
    alert_cooldown_s: int = 300         # délai minimal entre deux alertes de la sonde
    log_retention_days: int = 7         # résumés de 10 s
    stats_retention_days: int = 30      # coupures et résumés horaires
    vpn_shared_warn: bool = True        # avertir quand deux appareils semblent partager un profil VPN
    rsrp_warn_dbm: int = -105           # signal 4G/5G (application) : palier orange
    rsrp_alert_dbm: int = -115          # palier rouge
    sinr_warn_db: int = 3               # rapport signal/bruit : palier orange
    sinr_alert_db: int = 0              # palier rouge


BREIZH_DEFAULT_PORT = 47100
BREIZH_KEY_FILE = "breizh.key"     # à côté de station.toml quand key_file est vide
# Réseaux admis pour [breizh] host : le micro circule EN CLAIR, jamais vers une adresse publique.
BREIZH_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8",
    "fd00::/8", "fe80::/10", "::1/128"))


@dataclass
class Breizh:
    """Breizh Audio Box dans la chaîne d'émission (docs/breizh-cahier-des-charges.md). Réglages de la station ;
    la clé d'appairage est dans un fichier à part (key_file), le volume retour dans state_dir/breizh.json."""
    enabled: bool = False             # fonction disponible sur cette station
    host: str = ""                    # adresse IP PRIVÉE du PC de Breizh (pas de nom d'hôte)
    port: int = BREIZH_DEFAULT_PORT   # port UDP de Breizh
    key_file: str = ""                # clé d'appairage ; vide = breizh.key à côté de station.toml
    block_timeout_ms: int = 40        # bloc pas revenu à temps : il part « sec » à fallback_gain_db
    lost_ms: int = 100                # aucun retour valable pendant ce délai : repli en direct
    fallback_gain_db: float = -6.0    # gain du son direct en repli
    reactivate_after_s: int = 60      # stabilité exigée avant le retour automatique (0 = seulement à la main)


PRESENCE_DEFAULT_RELAY = "https://rf-diy.com/orx-relay/public"   # relais de rf-diy.com (sous-dossier : offre OVH sans sous-domaine libre)
PRESENCE_KEY_FILE = "presence.key"   # dans state_dir/presence/ quand key_file est vide
# Relais : https:// obligatoire ; http:// permis SEULEMENT vers la machine elle-même (essais avec un relais local).
_PRESENCE_RELAY_RE = re.compile(r"(https://[a-z0-9.-]{1,100}|http://(127\.0\.0\.1|localhost))(:\d{1,5})?(/[A-Za-z0-9._~-]+)*")


@dataclass
class Presence:
    """Présence de groupe (docs/presence-cahier-des-charges.md) : module « presence », sans AUCUN droit sur le poste.
    Groupes, partage, pseudo et clés de groupe sont dans state_dir/presence/ (choisis depuis la page, l'application
    ou TRX Console), jamais ici."""
    enabled: bool = False             # false : le module attend sans rien envoyer
    relay_url: str = PRESENCE_DEFAULT_RELAY   # relais (https:// ; http:// seulement vers 127.0.0.1 pour les essais)
    key_file: str = ""                # clés de la station ; vide = state_dir/presence/presence.key


MONLINK_KEY_FILE = "monlink.key"     # dans state_dir/monlink/ quand key_file est vide


@dataclass
class MonitorLink:
    """Monitoring inter-stations (docs/cdc-monitoring.md § 17) : module « monlink », sans AUCUN droit sur le poste.
    Liaisons, profils d'envoi et pseudo sont dans state_dir/monlink/ (choisis dans TRX Console), jamais ici. Clés À
    PART de la présence (décision de l'utilisateur du 2026-11-16) : les deux services ne peuvent pas être reliés."""
    enabled: bool = False             # false : le module attend sans rien envoyer ni relever
    relay_url: str = PRESENCE_DEFAULT_RELAY   # même relais que la présence (routes /v1/mon/)
    key_file: str = ""                # clés du monitoring ; vide = state_dir/monlink/monlink.key


@dataclass
class Diffusion:
    """Diffusion en direct du TRX vers des internautes (docs/diffusion-cahier-des-charges.md, docs/protocole-diffusion.md) :
    module « diffusion », sans AUCUN droit sur le poste. Aucun serveur imposé (rien par défaut). Secrets (mot de passe
    source, clé des métadonnées, identifiants des auditeurs) dans key_file (0600), JAMAIS ici."""
    enabled: bool = False             # false : le module attend sans rien envoyer
    server: str = ""                  # nom du serveur de diffusion (ex. diffusion.example.org)
    station: str = ""                 # nom de la station sur ce serveur (a-z 0-9 -), donné par son administrateur
    source_port: int = 8443           # port TLS des sources (Icecast lui-même, pas le port 443)
    api_port: int = 443               # HTTPS des métadonnées et de la page des auditeurs
    codec: str = "opus"               # opus (défaut, 32 kb/s) ou mp3 (64 kb/s : anciens iPhone, applications de radio)
    audio_port: int = 47822           # son de la passerelle vers le module : UDP en 127.0.0.1 SEULEMENT
    key_file: str = ""                # vide = state_dir/diffusion/diffusion.key
    tls: bool = True                  # false SEULEMENT vers 127.0.0.1 (faux serveur d'essai)
    # Décision de l'utilisateur (2026-11-17) : l'opérateur décide ce qui est diffusé. false : SILENCE pour les auditeurs
    # quand la réception sort des [[bands]] (ou fréquence inconnue), sans arrêter la diffusion ; true : tout est diffusé.
    # Même principe que [access] listeners_outside_bands des visiteurs, réglages indépendants.
    outside_bands: bool = False


@dataclass
class RemoteConsole:
    """TRX Console sur le réseau (étape 233, décisions de l'utilisateur du 2026-11-17) : la console web servie en HTTPS
    sur le réseau local ou le VPN, connexion avec un compte OPÉRATEUR marqué `admin = true`, session fermée après
    `idle_min` minutes sans action. Programme à part de la passerelle, sous le compte Linux `account` (jamais root) :
    le mot de passe sudo reste demandé dans le terminal, une fois par session. Réglé par le menu 4.6.
    (0.176.0-0.177.0 : raccourci SSH ; ses clés ssh_user / ssh_port / web_port sont reprises ou ignorées.)"""
    enabled: bool = False             # false : service arrêté
    account: str = ""                 # compte Linux sous lequel tourne la console (Debian, Pi) ; vide sous Windows
    port: int = 8444                  # port HTTPS de la console (adresse d'écoute : [network] gateway_bind)
    idle_min: int = 30                # session fermée après ce temps sans action (minutes)


@dataclass
class Freedv:
    """FreeDV RADE V1 en RÉCEPTION (lot F1, cahier des charges FreeDV) : deux décodeurs en processus enfants de la
    passerelle (trxstation/freedv/). Le choix du mode FreeDV (voix décodée à la place du son du poste) se fait depuis
    la page ou l'application, jamais ici ; il n'est pas gardé au redémarrage."""
    enabled: bool = False             # fonction disponible sur cette station (décodeurs installés)
    ka9q_path: str = "freedv-ka9q"    # voix décodée et indicatif (freedv-integrations) ; nom seul = cherché dans le PATH
    radae_rx_path: str = "radae_rx"   # synchro, SNR et décalage (rade_c) ; nom seul = cherché dans le PATH
    locator: str = ""                 # locator Maidenhead de la station (4 ou 6 caractères) : distances et note de la
                                      # liste « Activité FreeDV » (module freedv_activity) ; vide = sans distance


# Cadences d'échantillonnage permises et largeur de filtre FI associée (kHz, API SDRplay), mesurées à l'essai S0.
SDR_RATES = {2_000_000: 1536, 6_000_000: 5000, 8_000_000: 8000}     # SDRplay : largeur -> filtre du tuner (kHz)
RTL_RATES = (1_024_000, 2_048_000, 2_400_000)                       # clés RTL-SDR (8 bits, 2,4 MHz au plus sans pertes)
SDR_DRIVERS = ("sdrplay", "rtlsdr")


def sdr_rates(driver: str) -> tuple[int, ...]:
    """Largeurs permises pour ce pilote."""
    return RTL_RATES if driver == "rtlsdr" else tuple(SDR_RATES)


@dataclass
class Sdr:
    """Module SDR (docs/sdr-cahier-des-charges.md) : récepteur SDR en parallèle du TRX, RÉCEPTION SEULE, lancé comme
    module (« sdr » dans [modules] run). Le SDR est désigné par son NUMÉRO DE SÉRIE, jamais par son port."""
    enabled: bool = False             # fonction offerte aux opérateurs (exige « sdr » dans [modules] run)
    driver: str = "sdrplay"           # sdrplay (API du fabricant, installée à la main) ou rtlsdr (clé RTL-SDR, librtlsdr)
    serial: str = ""                  # numéro de série du SDR de CETTE station (trx-sdr --list) ; obligatoire
    core_path: str = ""               # programme sdr-core ; vide = installé avec la station (venv/bin), sinon le PATH
    sample_rate_hz: int = 2_000_000   # 2, 6 ou 8 MHz : largeur du waterfall (2 MHz conseillé, voir le cahier § 16)
    center_hz: int = 7_100_000        # fréquence centrale au démarrage (la dernière choisie depuis la page est reprise)
    antenna: str = "A"                # entrée du RSP2 : A ou B
    lna_state: int = 2                # état du LNA (0 = gain maximal ; 0 à 8 sur le RSP2)
    gain_reduction_db: int = 50       # réduction de gain FI (20 à 59 dB), quand l'AGC de la FI est coupé
    agc: bool = True                  # AGC matériel de la FI : le SDR règle lui-même la réduction de gain FI
    audio_port: int = 47821           # son démodulé du module vers la passerelle : UDP en 127.0.0.1 SEULEMENT
    fft_size: int = 4096              # points de la FFT (512 à 16384, puissance de 2)
    bins: int = 1024                  # cases d'une ligne envoyée aux clients (128 à fft_size, puissance de 2)
    lines_per_s: int = 8              # lignes de waterfall par seconde (1 à 15)
    max_cpu_pct: int = 150            # plafond du module (sdr-core + module), % d'UN cœur : au-delà, il se bride
    max_mem_mb: int = 400             # plafond de mémoire du module (sdr-core + module), Mo


@dataclass
class Tools:
    hamlib_dir: str = ""           # dossier d'installation de Hamlib (Windows) ; vide = PATH


@dataclass
class Network:
    rigctld_host: str = "127.0.0.1"   # rigctld ne doit JAMAIS écouter ailleurs qu'en local
    rigctld_port: int = 4532
    gateway_bind: str = "127.0.0.1"   # 127.0.0.1 = machine seule ; sinon IP du VPN ou 0.0.0.0 (voir docs/acces-distant.md)
    gateway_port: int = 8443
    web_client: bool = True           # sert la page web de contrôle sur le même port
    tls_cert: str = ""                # certificat TLS (PEM) : HTTPS natif, sans proxy devant
    tls_key: str = ""                 # clé privée correspondante
    allow_insecure_http: bool = False  # écoute HORS boucle locale sans TLS : à n'accepter que dans un VPN
    trusted_proxies: list[str] = field(default_factory=lambda: ["127.0.0.1", "::1"])  # IP/CIDR crus pour X-Forwarded-For
    ice_servers: list[str] = field(default_factory=lambda: ["stun:stun.l.google.com:19302"])  # [] = réseau local/VPN seul


@dataclass
class Safety:
    tot_s: int = 90                   # durée d'émission max (modifiable depuis le smartphone)
    tot_ceiling_s: int = 120          # plafond du TOT (Pi uniquement)
    enforce_bands: bool = True        # la station refuse d'émettre hors [[bands]] ; false si le poste le fait déjà (ex. « TX limit » des Icom)
    warn_before_s: int = 10           # bip d'avertissement avant coupure
    heartbeat_interval_ms: int = 500  # cadence attendue des battements client en TX
    heartbeat_timeout_ms: int = 2000  # sans battement : retour RX
    rig_temp_warn_c: int = 40         # température du poste (TEMP_METER) : avertissement (page, ntfy)
    rig_temp_cut_c: int = 50          # au-delà : émission à distance coupée et refusée jusqu'au retour sous warn
    # Rediffusion d'un enregistrement de l'audio reçu (application) : ACCORDÉE UNE FOIS par l'assistant, à la demande
    # expresse de l'opérateur (responsabilité réglementaire : rediffuser une station à des tiers est en général interdit)
    allow_replay: bool = False


TEMP_MIN_C, TEMP_MAX_C = 20, 90      # bornes des seuils de température du poste
LOCAL_TX_CEILING_S = 600             # plafond de [supervisor] local_tx_max_s (décision de l'utilisateur, 2026-11-16)


@dataclass
class Supervisor:
    tot_abs_s: int = 135              # TOT absolu, strictement > plafond de la passerelle
    poll_interval_s: float = 1.0      # cadence au repos (0,25 s pendant une émission)
    max_reboots_per_hour: int = 3     # au-delà : mode sûr (RX, passerelle arrêtée)
    notify_url: str = ""              # ex. https://ntfy.sh/mon-sujet (optionnel)
    notify_lang: str = "fr"           # langue des alertes ntfy : fr ou en (celles du catalogue d'erreurs)
    status_path: str = field(default_factory=lambda: str(default_status_path()))  # écrit par la passerelle
    state_dir: str = field(default_factory=lambda: str(default_state_dir()))      # mode sûr, reboots
    service_mode: str = "auto"        # auto | systemd | managed (le superviseur lance les processus)
    instance_lock_port: int = 47321   # port local réservé : une seule instance du superviseur
    stale_after_s: float = 2.0        # passerelle muette si son fichier d'état ne change plus
    startup_grace_s: float = 30.0     # délai de grâce au démarrage (passerelle/rigctld pas encore prêts)
    mismatch_grace_s: float = 1.5     # tolérance avant de juger l'émission « inexpliquée »
    rigctld_fail_s: float = 5.0       # rigctld injoignable depuis ce délai : on le redémarre
    recovery_wait_s: float = 20.0     # attente entre deux niveaux de l'échelle de reprise
    healthy_reset_s: float = 120.0    # durée sans problème avant de repartir du niveau 0
    temp_alert_c: float = 70.0        # alerte seule (70 °C : décision de l'utilisateur, 2026-11-11)
    mem_alert_pct: int = 90           # mémoire utilisée au-delà (60 s de suite) : alerte seule, une par heure ; 0 = aucune
    disk_alert_pct: int = 70          # disque (dossier d'état et /) au-delà : alerte seule, une par heure ; 0 = aucune
    alive_every_h: float = 1.0        # battement « Station en service » par notify_url (priorité minimale) ; 0 = aucun
    allow_local_tx: bool = True       # True (« station partagée ») : l'émission locale (micro du poste) n'est pas coupée,
                                      # sauf par tot_abs_s ; False : coupée à chaque passage (jamais d'escalade si « T 0 » marche)
    local_tx_max_s: int = 300         # station partagée, opérateur PRÉSENT (action sur le poste, gateway/safety/local.py) :
                                      # émission locale tolérée jusque-là au lieu de tot_abs_s (étape 206) ; plafond 600 s ;
                                      # jamais moins que tot_abs_s (le plus grand des deux s'applique)
    gateway_unit: str = "trx-gateway.service"
    rigctld_unit: str = "rigctld.service"


@dataclass
class Modules:
    run: list[str] = field(default_factory=list)   # modules à faire tourner (ex. ["demo"]) ; vide = aucun, pas de bus
    bus_port: int = 47810             # API interne des modules : écoute UNIQUEMENT en 127.0.0.1
    run_as: str = "trx"               # Linux, superviseur root : compte d'exécution des modules (jamais root)
    extra_dir: str = ""               # dossier de modules supplémentaires (<nom>/manifest.toml) ; vide = modules fournis

    @property
    def enabled(self) -> bool:
        return bool(self.run)


@dataclass
class Spectrum:
    enabled: bool = False             # spectre HF du poste ; false = comme avant (un seul port, pas de waterfall HF)
    source: str = "rigctld"           # "rigctld" : Hamlib 4.6+ async + diffusion UDP locale (rejeté sous Windows avec un
                                      # IC-7300MK2) ; "civ_port" : second port série du poste réglé en CI-V (Icom)
    data_port: int = 4572             # source rigctld : port UDP de la diffusion, sur 127.0.0.1 SEULEMENT
    max_fps: int = 10                 # cadence maximale envoyée aux clients (images par seconde)
    port: str = ""                    # source civ_port : second port du poste (ex. COM7) ; JAMAIS le port CAT ou PTT
    civ_address: str = ""             # source civ_port : adresse CI-V du poste en hexadécimal (ex. B6), revérifiée à chaque ouverture
    baud: int = 115200                # source civ_port : débit du second port


SPECTRUM_SOURCES = ("rigctld", "civ_port")
CIV_BAUDS = (9600, 19200, 38400, 57600, 115200)


def is_icom_model(model: int) -> bool:
    """Modèles Hamlib du pilote Icom (numéros 3001 à 3999)."""
    return 3000 < model < 4000


def parse_civ_address(text: str) -> int | None:
    """« B6 », « b6 » ou « 0xB6 » -> 0xB6 ; None si invalide (01 à DF)."""
    t = text.strip().lower().removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{1,2}", t):
        return None
    value = int(t, 16)
    return value if 0x01 <= value <= 0xDF else None


# Options -C de rigctld réservées à [spectrum] : jamais dans extra_conf (le serveur de commandes UDP de Hamlib
# n'a AUCUNE authentification et pourrait mettre le poste en émission ; la diffusion doit rester locale).
RESERVED_RIGCTLD_CONF = ("async", "multicast_data_addr", "multicast_data_port", "multicast_cmd_addr", "multicast_cmd_port")
# Cache de rigctld COUPÉ (étape 176) : avec un cache (Hamlib 4.0+, 500 ms en 4.x, 1000 en 5.0), rigctld renvoie après
# « T 0 » la valeur COMMANDÉE à la relecture du PTT sans interroger le poste : un poste resté en émission paraîtrait
# coupé. Ajouté par la station à chaque lancement ; interdit dans extra_conf.
NO_CACHE_CONF = "cache_timeout=0"
SAFETY_RIGCTLD_CONF = ("cache_timeout",)
SPECTRUM_MIN_SPEED = 115200


def spectrum_rigctld_conf(cfg: "Config") -> list[str]:
    """Options de rigctld pour le spectre (vide si désactivé) : diffusion vers 127.0.0.1, commandes UDP coupées."""
    if not cfg.spectrum.enabled or cfg.spectrum.source != "rigctld":
        return []
    return ["-C", f"async=1,multicast_data_addr=127.0.0.1,multicast_data_port={cfg.spectrum.data_port},"
                  "multicast_cmd_addr=0.0.0.0"]


def _conf_keys(entries: list[str]) -> list[str]:
    """Noms des options d'une liste « -C » (chaque entrée peut en grouper plusieurs : a=1,b=2)."""
    return [item.split("=", 1)[0].strip().lower() for entry in entries for item in str(entry).split(",") if item.strip()]


@dataclass
class Update:
    enabled: bool = True              # cherche une nouvelle version au démarrage puis toutes les 24 h (rien n'est installé sans confirmation)
    allow_prerelease: bool = False    # true : propose aussi les pré-versions publiées sur GitHub


SELCALL_FILTER_MODES = ("mute", "attenuate", "chime")


@dataclass
class Selcall:
    """SELCALL : squelch numérique par appel de groupe (docs/selcall-cahier-des-charges.md). Réglages de la station ;
    l'état (veille, ouvert), le code armé et l'historique sont dans un fichier d'état à part (state_dir/selcall.json)."""
    enabled: bool = False             # fonction disponible sur cette station
    send_on_tx_end: bool = False      # trame émise en fin d'émission, à la place du roger bip (lot 3)
    manual_repeat: int = 3            # appel manuel : nombre d'émissions de la trame (1 à 5)
    manual_gap_ms: int = 500          # appel manuel : silence entre deux trames
    filter_mode: str = "attenuate"    # tonalités SELCALL dans l'audio reçu : mute | attenuate | chime
    attenuation_db: int = 20          # mode attenuate
    audio_delay_ms: int = 500         # retard de l'audio reçu (250 à 1 000 ms) : les tons sont filtrés avant d'être entendus
    tx_level_dbfs: float = -6.0       # niveau de la trame émise (sous le seuil d'ALC)
    notify_on_call: bool = True       # alerte ntfy (passerelle) quand un appel ouvre le squelch, sans le code
    history_size: int = 10            # derniers codes gardés


CLUSTER_SOURCE_TYPES = ("telnet", "rbn", "web")     # telnet = cluster radioamateur ; web = page clusterdx.org (CB)
_CLUSTER_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


@dataclass
class ClusterSource:
    name: str
    type: str = "telnet"              # telnet (cluster DX), rbn (Reverse Beacon Network), web (clusterdx.org, cibistes)
    host: str = ""                    # telnet, rbn
    port: int = 0
    url: str = ""                     # web : https seulement
    call: str = ""                    # vide = [cluster] call
    secret: str = ""                  # NOM d'un mot de passe dans secrets.toml (jamais le mot de passe) ; vide = aucun
    priority: int = 1                 # clusters telnet : 1 = principal, puis secours
    enabled: bool = True


@dataclass
class Cluster:
    enabled: bool = False             # module Cluster DX (spots des clusters, du RBN, des cibistes)
    call: str = ""                    # VOTRE indicatif radioamateur, seul envoyé aux clusters et au RBN ; vide = activation refusée
    cb_call: str = ""                 # votre indicatif de cibiste (sources CB) ; aujourd'hui envoyé nulle part (page publique)
    modes: list[str] = field(default_factory=list)       # modes suivis (CW SSB AM FM FREEDV) ; vide = tous ; jamais le numérique
    bands: list[str] = field(default_factory=list)       # vide = toutes
    continents: list[str] = field(default_factory=list)  # continent du SPOTTEUR ; vide = tous
    blacklist: list[str] = field(default_factory=list)   # indicatifs ignorés ; « XX* » = préfixe
    ttl_min: float = 15.0             # durée de vie des spots de cluster et des cibistes
    rbn_ttl_min: float = 10.0         # durée de vie des spots du RBN
    cty_update: bool = True           # mise à jour hebdomadaire de cty.dat (pays des indicatifs)
    source: list[ClusterSource] = field(default_factory=list)


def validate_cluster(c: Cluster, modules: "Modules") -> list[str]:
    """Erreurs bloquantes de [cluster] (contrôlées même désactivé, sauf l'indicatif et les sources actives)."""
    from .cluster.bandplan import BAND_NAMES, MODES
    from .cluster.cty import CONTINENTS
    from .cluster.text import own_call_problem
    p: list[str] = []
    for name in ("enabled", "cty_update"):
        if not isinstance(getattr(c, name), bool):
            p.append(_t("bool", where="[cluster]", name=name))
    for key, values, allowed in (("modes", c.modes, MODES), ("bands", c.bands, BAND_NAMES),
                                 ("continents", c.continents, CONTINENTS)):
        if not isinstance(values, list) or any(v not in allowed for v in values):
            p.append(_t("cluster.values", key=key, allowed=' '.join(allowed)))
    if not isinstance(c.blacklist, list) or any(not isinstance(b, str) or not re.fullmatch(r"[A-Z0-9/]{1,15}\*?", b)
                                                for b in c.blacklist):
        p.append(_t("cluster.blacklist"))
    if c.cb_call and own_call_problem(c.cb_call):
        p.append(f"[cluster] cb_call : {own_call_problem(c.cb_call)}")
    for key in ("ttl_min", "rbn_ttl_min"):
        v = getattr(c, key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 120:
            p.append(_t("cluster.ttl", key=key))
    names: set[str] = set()
    for s in c.source:
        label = f"[[cluster.source]] « {s.name} »"
        if not isinstance(s.name, str) or not _CLUSTER_NAME_RE.fullmatch(s.name):
            p.append(_t("cluster.source_name", name=repr(s.name)))
        elif s.name in names:
            p.append(_t("cluster.source_duplicate", label=label))
        names.add(s.name)
        if s.type not in CLUSTER_SOURCE_TYPES:
            p.append(_t("cluster.source_type", label=label, types=' ou '.join(CLUSTER_SOURCE_TYPES)))
        elif s.type == "web":
            if not isinstance(s.url, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s\"']*)?", s.url):
                p.append(_t("cluster.source_url", label=label))
        else:
            if not isinstance(s.host, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", s.host or ""):
                p.append(_t("cluster.source_host", label=label))
            if isinstance(s.port, bool) or not isinstance(s.port, int) or not 1 <= s.port <= 65535:
                p.append(_t("cluster.source_port", label=label))
        if s.call and own_call_problem(s.call):
            p.append(f"{label} : call : {own_call_problem(s.call)}")
        if s.secret and (not isinstance(s.secret, str) or not _CLUSTER_NAME_RE.fullmatch(s.secret)):
            p.append(_t("cluster.source_secret", label=label))
        if not isinstance(s.enabled, bool):
            p.append(_t("bool_at", where=label, name="enabled"))
        if isinstance(s.priority, bool) or not isinstance(s.priority, int) or not 1 <= s.priority <= 99:
            p.append(_t("cluster.source_priority", label=label))
    if c.enabled is True:
        active = [s for s in c.source if s.enabled is True]
        if not active:
            p.append(_t("cluster.no_source"))
        if any(s.type != "web" and not s.call for s in active) and own_call_problem(c.call):
            p.append(_t("cluster.call_required", problem=own_call_problem(c.call)))
        if "cluster" not in modules.run:
            p.append(_t("module_not_run", where="[cluster]", module="cluster"))
    return p


@dataclass
class Band:
    name: str
    low_mhz: float
    high_mhz: float


# Points de départ pour la région 1 de l'IARU. À VÉRIFIER ET ADAPTER à ta licence et à ton pays.
DEFAULT_BANDS_R1 = (
    Band("160m", 1.810, 2.000), Band("80m", 3.500, 3.800), Band("60m", 5.3515, 5.3665),
    Band("40m", 7.000, 7.200), Band("30m", 10.100, 10.150), Band("20m", 14.000, 14.350),
    Band("17m", 18.068, 18.168), Band("15m", 21.000, 21.450), Band("12m", 24.890, 24.990),
    Band("10m", 28.000, 29.700), Band("2m", 144.000, 146.000), Band("70cm", 430.000, 440.000),
)


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    config_revision: int = 1
    rig: Rig = field(default_factory=Rig)
    audio: Audio = field(default_factory=Audio)
    tools: Tools = field(default_factory=Tools)
    network: Network = field(default_factory=Network)
    safety: Safety = field(default_factory=Safety)
    supervisor: Supervisor = field(default_factory=Supervisor)
    modules: Modules = field(default_factory=Modules)
    update: Update = field(default_factory=Update)
    spectrum: Spectrum = field(default_factory=Spectrum)
    cluster: Cluster = field(default_factory=Cluster)
    selcall: Selcall = field(default_factory=Selcall)
    access: Access = field(default_factory=Access)
    swr: Swr = field(default_factory=Swr)
    breizh: Breizh = field(default_factory=Breizh)
    netprobe: Netprobe = field(default_factory=Netprobe)
    presence: Presence = field(default_factory=Presence)
    monitor_link: MonitorLink = field(default_factory=MonitorLink)
    diffusion: Diffusion = field(default_factory=Diffusion)
    remote_console: RemoteConsole = field(default_factory=RemoteConsole)
    freedv: Freedv = field(default_factory=Freedv)
    sdr: Sdr = field(default_factory=Sdr)
    bands: list[Band] = field(default_factory=list)
    clients: list[ClientAuth] = field(default_factory=list)

    def tx_allowed(self, freq_hz: float) -> bool:
        """Vrai si la fréquence est dans une bande autorisée. Liste vide = jamais."""
        mhz = freq_hz / 1e6
        return any(b.low_mhz <= mhz <= b.high_mhz for b in self.bands)


def validate(cfg: Config) -> list[str]:
    """Retourne la liste des erreurs bloquantes (vide si la config est valide)."""
    p: list[str] = []
    if cfg.schema_version != SCHEMA_VERSION:
        p.append(_t("schema_version", version=cfg.schema_version, expected=SCHEMA_VERSION))

    r = cfg.rig
    if not isinstance(r.model, int) or r.model <= 0:
        p.append(_t("rig.model"))
    elif r.model != DUMMY_MODEL and not r.port:
        p.append(_t("rig.port"))
    if not 0 <= r.max_power_w <= 2000:
        p.append(_t("rig.max_power_w"))
    if not isinstance(r.tuner, bool):
        p.append(_t("rig.tuner"))
    for mode in r.tx_modes:
        if not re.fullmatch(r"[A-Za-z0-9\-]{1,16}", mode):
            p.append(_t("rig.tx_modes", mode=mode))
    if r.ptt_type not in PTT_TYPES:
        p.append(_t("rig.ptt_type", ptt_type=r.ptt_type, choices=', '.join(PTT_TYPES)))
    if r.speed is not None and r.speed <= 0:
        p.append(_t("positive", where="[rig]", name="speed"))

    if cfg.audio.sample_rate != 48000:
        p.append(_t("audio.sample_rate"))
    for name in ("rx_gain_db", "tx_gain_db"):
        if not -40 <= getattr(cfg.audio, name) <= 20:
            p.append(_t("audio.gain", name=name))
    seen: set[str] = set()
    for client in cfg.clients:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", client.id):
            p.append(_t("clients.id_invalid", id=repr(client.id)))
        elif client.id in seen:
            p.append(_t("clients.id_duplicate", id=client.id))
        seen.add(client.id)
        if bool(client.password_hash) == bool(client.token):
            p.append(_t("clients.one_secret", id=client.id))
        elif client.password_hash and not is_valid_hash(client.password_hash):
            p.append(_t("clients.bad_hash", id=client.id))
        elif client.token and len(client.token) < 16:
            p.append(_t("clients.short_token", id=client.id))
        p += _client_problems(client, cfg.clients)
    p += _access_problems(cfg.access)
    p += _swr_problems(cfg.swr)
    p += _netprobe_problems(cfg.netprobe)
    p += _breizh_problems(cfg.breizh, cfg)
    p += _presence_problems(cfg.presence)
    p += _monitor_link_problems(cfg.monitor_link, cfg.modules)
    p += _diffusion_problems(cfg.diffusion, cfg.modules, cfg.sdr)
    p += _remote_console_problems(cfg)
    p += _freedv_problems(cfg.freedv)
    p += _sdr_problems(cfg.sdr, cfg.modules)
    if bool(cfg.network.tls_cert) != bool(cfg.network.tls_key):
        p.append(_t("network.tls_pair"))
    for proxy in cfg.network.trusted_proxies:
        try:
            ipaddress.ip_network(proxy, strict=False)
        except ValueError:
            p.append(_t("network.trusted_proxies", proxy=proxy))
    for server in cfg.network.ice_servers:
        if not re.fullmatch(r"(stun|turn)s?:[^\s]+", server):
            p.append(_t("network.ice_servers", server=server))

    n = cfg.network
    if n.rigctld_host not in ("127.0.0.1", "localhost", "::1"):
        p.append(_t("network.rigctld_host"))
    for name, port in (("rigctld_port", n.rigctld_port), ("gateway_port", n.gateway_port)):
        if not 1 <= port <= 65535:
            p.append(_t("out_of_range", where="[network]", name=name))

    s = cfg.safety
    if not 0 < s.tot_s <= s.tot_ceiling_s:
        p.append(_t("safety.tot", tot=s.tot_s, ceiling=s.tot_ceiling_s))
    if not 0 < s.warn_before_s < s.tot_s:
        p.append(_t("safety.warn_before", warn=s.warn_before_s, tot=s.tot_s))
    if s.heartbeat_interval_ms <= 0 or s.heartbeat_timeout_ms < 2 * s.heartbeat_interval_ms:
        p.append(_t("safety.heartbeat"))
    if not isinstance(s.allow_replay, bool):
        p.append(_t("bool", where="[safety]", name="allow_replay"))
    if not TEMP_MIN_C <= s.rig_temp_warn_c < s.rig_temp_cut_c <= TEMP_MAX_C:
        p.append(_t("safety.rig_temp", warn=s.rig_temp_warn_c, cut=s.rig_temp_cut_c, low=TEMP_MIN_C, high=TEMP_MAX_C))

    v = cfg.supervisor
    if v.tot_abs_s <= s.tot_ceiling_s:
        p.append(_t("supervisor.tot_abs"))
    if isinstance(v.local_tx_max_s, bool) or not isinstance(v.local_tx_max_s, int)             or not 0 < v.local_tx_max_s <= LOCAL_TX_CEILING_S:
        # pas de borne basse liée à tot_abs_s : une station.toml existante resterait refusée ; le superviseur prend le
        # plus grand des deux (jamais moins que le TOT absolu)
        p.append(_t("supervisor.local_tx_max", ceiling=LOCAL_TX_CEILING_S))
    if v.max_reboots_per_hour < 0:
        p.append(_t("not_negative", where="[supervisor]", name="max_reboots_per_hour"))
    if v.stale_after_s < 0.5:
        p.append(_t("supervisor.stale_after"))
    for name in ("poll_interval_s", "recovery_wait_s", "healthy_reset_s", "rigctld_fail_s", "temp_alert_c"):
        if getattr(v, name) <= 0:
            p.append(_t("positive", where="[supervisor]", name=name))
    for name in ("startup_grace_s", "mismatch_grace_s"):
        if getattr(v, name) < 0:
            p.append(_t("not_negative", where="[supervisor]", name=name))
    for name in ("mem_alert_pct", "disk_alert_pct"):
        value = getattr(v, name)
        if isinstance(value, bool) or not isinstance(value, int) or not (value == 0 or 50 <= value <= 99):
            p.append(_t("supervisor.alert_pct", name=name))
    if v.alive_every_h != 0 and not 0.25 <= v.alive_every_h <= 168:
        p.append(_t("supervisor.alive_every_h"))
    if v.service_mode not in ("auto", "systemd", "managed"):
        p.append(_t("supervisor.service_mode"))
    if not 1 <= v.instance_lock_port <= 65535:
        p.append(_t("out_of_range", where="[supervisor]", name="instance_lock_port"))
    if not v.status_path or not v.state_dir:
        p.append(_t("supervisor.paths"))
    if v.notify_url and not v.notify_url.startswith(("https://", "http://")):
        p.append(_t("supervisor.notify_url"))
    if v.notify_lang not in ("fr", "en"):
        p.append(_t("supervisor.notify_lang"))

    m = cfg.modules
    for name in m.run:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", name):
            p.append(_t("modules.run_name", name=name))
    if len(set(m.run)) != len(m.run):
        p.append(_t("modules.run_twice"))
    if not 1024 <= m.bus_port <= 65535:
        p.append(_t("modules.bus_port_range"))
    elif m.bus_port in (n.gateway_port, n.rigctld_port, v.instance_lock_port):
        p.append(_t("modules.bus_port_clash"))
    if m.run_as and not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", m.run_as):
        p.append(_t("modules.run_as", account=m.run_as))
    elif m.run_as == "root":
        p.append(_t("modules.run_as_root"))

    for name in ("enabled", "allow_prerelease"):
        if not isinstance(getattr(cfg.update, name), bool):
            p.append(_t("bool", where="[update]", name=name))

    sc = cfg.selcall
    for name in ("enabled", "send_on_tx_end", "notify_on_call"):
        if not isinstance(getattr(sc, name), bool):
            p.append(_t("bool", where="[selcall]", name=name))
    ranges = {"manual_repeat": (1, 5), "manual_gap_ms": (200, 3000), "attenuation_db": (6, 60),
              "audio_delay_ms": (250, 1000), "history_size": (1, 50)}
    for name, (lo, hi) in ranges.items():
        v = getattr(sc, name)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            p.append(_t("int_range_expected", where="[selcall]", name=name, low=lo, high=hi))
    if sc.filter_mode not in SELCALL_FILTER_MODES:
        p.append(_t("selcall.filter_mode", modes=' | '.join(SELCALL_FILTER_MODES)))
    if not isinstance(sc.tx_level_dbfs, (int, float)) or isinstance(sc.tx_level_dbfs, bool) or not -30 <= sc.tx_level_dbfs <= -1:
        p.append(_t("selcall.tx_level"))

    sp = cfg.spectrum
    reserved = sorted(set(_conf_keys(r.extra_conf)) & set(RESERVED_RIGCTLD_CONF))
    if reserved:
        p.append(_t("rig.extra_conf_reserved", keys=', '.join(reserved)))
    if set(_conf_keys(r.extra_conf)) & set(SAFETY_RIGCTLD_CONF):
        p.append(_t("rig.extra_conf_cache"))
    if not isinstance(sp.enabled, bool):
        p.append(_t("bool", where="[spectrum]", name="enabled"))
    if isinstance(sp.data_port, bool) or not isinstance(sp.data_port, int) or not 1024 <= sp.data_port <= 65535:
        p.append(_t("spectrum.data_port"))
    if isinstance(sp.max_fps, bool) or not isinstance(sp.max_fps, int) or not 1 <= sp.max_fps <= 20:
        p.append(_t("spectrum.max_fps"))
    if sp.source not in SPECTRUM_SOURCES:
        p.append(_t("spectrum.source", sources=' ou '.join(SPECTRUM_SOURCES)))
    if sp.enabled is True and sp.source == "civ_port":
        same = {x.strip().lower() for x in (r.port, r.ptt_port) if x and x.strip()}
        if not isinstance(sp.port, str) or not sp.port.strip():
            p.append(_t("spectrum.port_missing"))
        elif sp.port.strip().lower() in same:
            p.append(_t("spectrum.port_is_cat", port=sp.port))
        if not isinstance(sp.civ_address, str) or parse_civ_address(sp.civ_address) is None:
            p.append(_t("spectrum.civ_address"))
        if sp.baud not in CIV_BAUDS:
            p.append(_t("spectrum.baud", bauds=', '.join(map(str, CIV_BAUDS))))
        if not is_icom_model(r.model):
            p.append(_t("spectrum.icom_only"))
    if sp.enabled is True and sp.source == "rigctld" and r.speed and r.speed < SPECTRUM_MIN_SPEED:
        p.append(_t("spectrum.speed", min_speed=SPECTRUM_MIN_SPEED, speed=r.speed))

    for b in cfg.bands:
        if not 0 < b.low_mhz < b.high_mhz:
            p.append(_t("bands.limits", name=b.name))
    p += validate_cluster(cfg.cluster, cfg.modules)
    return p


def _client_problems(client: ClientAuth, clients: list[ClientAuth]) -> list[str]:
    """Rôle, pseudo, activation et expiration d'un compte. Un rôle inconnu est BLOQUANT : une faute de frappe ne doit
    jamais donner un compte opérateur."""
    p, where = [], f"[[clients]] {client.id}"
    if client.role not in ROLES:
        p.append(_t("clients.role", where=where, role=client.role))
    if not isinstance(client.pseudo, str) or len(client.pseudo) > PSEUDO_MAX or client.pseudo != client.pseudo.strip() \
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in client.pseudo):
        p.append(_t("clients.pseudo_invalid", where=where, max=PSEUDO_MAX))
    elif client.pseudo and any(client.pseudo.casefold() == other.id.casefold() for other in clients):
        p.append(_t("clients.pseudo_is_id", where=where, pseudo=client.pseudo))
    if not isinstance(client.enabled, bool):
        p.append(_t("bool_at", where=where, name="enabled"))
    if not isinstance(client.admin, bool):
        p.append(_t("bool_at", where=where, name="admin"))
    elif client.admin and client.role != "operator":
        p.append(_t("clients.listener_admin", where=where))
    if not isinstance(client.expires, str) or (client.expires and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", client.expires)):
        p.append(_t("clients.expires_format", where=where))
    elif client.expires:
        try:
            date.fromisoformat(client.expires)
        except ValueError:
            p.append(_t("clients.expires_invalid", where=where, expires=client.expires))
    return p


def _access_problems(a: Access) -> list[str]:
    p = []
    for name, low, high in (("max_listeners", 0, 20), ("max_operators", 1, 8), ("operator_grace_s", 0, 600),
                            ("listener_spectrum_fps", 1, 20), ("overload_temp_c", 50, 105), ("overload_cpu_pct", 50, 100),
                            ("overload_lag_ms", 20, 2000), ("overload_mem_pct", 1, 50)):
        value = getattr(a, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            p.append(_t("int_between", where="[access]", name=name, low=low, high=high))
    for name in ("listeners_need_operator", "listeners_outside_bands"):
        if not isinstance(getattr(a, name), bool):
            p.append(_t("bool", where="[access]", name=name))
    return p


def _swr_problems(s: Swr) -> list[str]:
    p = []
    if not isinstance(s.enabled, bool):
        p.append(_t("bool", where="[swr]", name="enabled"))
    for name, low, high in (("max_power_pct", 5, 50), ("max_points", 2, 200)):
        value = getattr(s, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            p.append(_t("int_between", where="[swr]", name=name, low=low, high=high))
    value = s.point_tx_max_s
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.5 <= value <= 3.0:
        p.append(_t("number_between", where="[swr]", name="point_tx_max_s", low="0.5", high="3"))
    return p


def _number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _ip_text(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _netprobe_problems(n: Netprobe) -> list[str]:
    p = []
    for name in ("enabled", "vpn_shared_warn"):
        if not isinstance(getattr(n, name), bool):
            p.append(_t("bool", where="[netprobe]", name=name))
    if not _number(n.heartbeat_interval_s) or not 0.5 <= n.heartbeat_interval_s <= 10:
        p.append(_t("number_between", where="[netprobe]", name="heartbeat_interval_s", low="0.5", high="10"))
    for name, low, high in (("outage_missed_beats", 2, 20), ("rtt_warn_ms", 20, 5000), ("rtt_alert_ms", 20, 5000),
                            ("alert_outage_s", 0, 3600), ("alert_cooldown_s", 30, 86400),
                            ("log_retention_days", 1, 30), ("stats_retention_days", 7, 90),
                            ("rsrp_warn_dbm", -140, -40), ("rsrp_alert_dbm", -140, -40),
                            ("sinr_warn_db", -20, 30), ("sinr_alert_db", -20, 30)):
        value = getattr(n, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            p.append(_t("int_between", where="[netprobe]", name=name, low=low, high=high))
    for name in ("loss_warn_pct", "loss_alert_pct"):
        value = getattr(n, name)
        if not _number(value) or not 0.1 <= value <= 100:
            p.append(_t("number_between", where="[netprobe]", name=name, low="0.1", high="100"))
    if not p:
        for warn, alert in (("loss_warn_pct", "loss_alert_pct"), ("rtt_warn_ms", "rtt_alert_ms")):
            if getattr(n, warn) >= getattr(n, alert):
                p.append(_t("netprobe.warn_below_alert", warn=warn, alert=alert))
        if n.rsrp_alert_dbm >= n.rsrp_warn_dbm or n.sinr_alert_db >= n.sinr_warn_db:
            p.append(_t("netprobe.signal_thresholds"))
    if not isinstance(n.lan_target, str) or (n.lan_target != "auto" and not _ip_text(n.lan_target)):
        p.append(_t("netprobe.lan_target"))
    if not isinstance(n.internet_target, str) or (n.internet_target and not _ip_text(n.internet_target)):
        p.append(_t("netprobe.internet_target"))
    return p


def breizh_host_allowed(host: str) -> bool:
    """Adresse IP privée, de lien local ou locale (jamais un nom : pas de DNS dans le chemin du son)."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in net for net in BREIZH_NETWORKS if net.version == address.version)


def _breizh_problems(b: Breizh, cfg: Config) -> list[str]:
    p = []
    if not isinstance(b.enabled, bool):
        p.append(_t("bool", where="[breizh]", name="enabled"))
    if not isinstance(b.host, str) or (b.host and not breizh_host_allowed(b.host)):
        p.append(_t("breizh.host_private"))
    elif b.enabled is True and not b.host:
        p.append(_t("breizh.host_required"))
    if not isinstance(b.key_file, str):
        p.append(_t("path", where="[breizh]", name="key_file"))
    ints = {"port": (1024, 65535), "block_timeout_ms": (15, 100), "lost_ms": (50, 500)}
    for name, (low, high) in ints.items():
        value = getattr(b, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            p.append(_t("int_between", where="[breizh]", name=name, low=low, high=high))
    if (isinstance(b.block_timeout_ms, int) and isinstance(b.lost_ms, int)
            and not isinstance(b.lost_ms, bool) and b.lost_ms <= b.block_timeout_ms):
        p.append(_t("breizh.lost_ms"))
    value = b.fallback_gain_db
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -20 <= value <= 0:
        p.append(_t("breizh.fallback_gain"))
    value = b.reactivate_after_s
    if isinstance(value, bool) or not isinstance(value, int) or not (value == 0 or 30 <= value <= 3600):
        p.append(_t("breizh.reactivate"))
    if isinstance(b.host, str) and b.host and is_loopback(b.host) and b.port in (
            cfg.network.gateway_port, cfg.network.rigctld_port, cfg.modules.bus_port, cfg.supervisor.instance_lock_port):
        p.append(_t("breizh.port_taken"))
    return p


def _presence_problems(pr: Presence) -> list[str]:
    p = []
    if not isinstance(pr.enabled, bool):
        p.append(_t("bool", where="[presence]", name="enabled"))
    if not isinstance(pr.relay_url, str) or not _PRESENCE_RELAY_RE.fullmatch(pr.relay_url):
        p.append(_t("relay_url", where="[presence]"))
    if not isinstance(pr.key_file, str):
        p.append(_t("path", where="[presence]", name="key_file"))
    return p


_LOCATOR = re.compile(r"^[A-R]{2}[0-9]{2}([A-X]{2})?$")


def _freedv_problems(fd: Freedv) -> list[str]:
    p = []
    if not isinstance(fd.enabled, bool):
        p.append(_t("bool", where="[freedv]", name="enabled"))
    for name in ("ka9q_path", "radae_rx_path"):
        value = getattr(fd, name)
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
            p.append(_t("freedv.program", name=name))
    if not isinstance(fd.locator, str) or (fd.locator.strip() and not _LOCATOR.match(fd.locator.strip().upper())):
        p.append(_t("freedv.locator"))
    return p


_SDR_SERIAL = re.compile(r"^[A-Za-z0-9]{4,32}$")


def _pow2(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0 and v & (v - 1) == 0


def _sdr_problems(sd: Sdr, modules: Modules) -> list[str]:
    p = []
    if not isinstance(sd.enabled, bool):
        p.append(_t("bool", where="[sdr]", name="enabled"))
    if sd.driver not in SDR_DRIVERS:
        p.append(_t("sdr.driver", drivers=', '.join(SDR_DRIVERS)))
    if not isinstance(sd.serial, str) or (sd.serial and not _SDR_SERIAL.match(sd.serial)):
        p.append(_t("sdr.serial"))
    if not isinstance(sd.core_path, str) or any(c in sd.core_path for c in "\r\n\0"):
        p.append(_t("sdr.core_path"))
    if sd.sample_rate_hz not in sdr_rates(sd.driver):
        p.append(_t("sdr.sample_rate", driver=sd.driver, rates=", ".join(str(r) for r in sdr_rates(sd.driver))))
    for name, lo, hi in (("center_hz", 1_000, 2_000_000_000), ("lna_state", 0, 8), ("gain_reduction_db", 20, 59),
                         ("lines_per_s", 1, 15),      # le bus limite un module à 20 messages par seconde
                         ("max_cpu_pct", 20, 800), ("max_mem_mb", 50, 4000)):
        v = getattr(sd, name)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            p.append(_t("int_range", where="[sdr]", name=name, low=lo, high=hi))
    if sd.antenna not in ("A", "B"):
        p.append(_t("sdr.antenna"))
    if not isinstance(sd.agc, bool):
        p.append(_t("bool", where="[sdr]", name="agc"))
    if isinstance(sd.audio_port, bool) or not isinstance(sd.audio_port, int) or not 1024 <= sd.audio_port <= 65535:
        p.append(_t("sdr.audio_port_range"))
    elif sd.audio_port == modules.bus_port:
        p.append(_t("sdr.audio_port_bus"))
    if not _pow2(sd.fft_size) or not 512 <= sd.fft_size <= 16384:
        p.append(_t("sdr.fft_size"))
    if not _pow2(sd.bins) or not 128 <= sd.bins <= min(16384, sd.fft_size if isinstance(sd.fft_size, int) else 16384):
        p.append(_t("sdr.bins"))
    if sd.enabled is True:
        if not sd.serial:
            p.append(_t("sdr.no_serial"))
        if "sdr" not in modules.run:
            p.append(_t("module_not_run", where="[sdr]", module="sdr"))
    return p


def _monitor_link_problems(ml: MonitorLink, modules: Modules) -> list[str]:
    p = []
    if not isinstance(ml.enabled, bool):
        p.append(_t("bool", where="[monitor_link]", name="enabled"))
    if not isinstance(ml.relay_url, str) or not _PRESENCE_RELAY_RE.fullmatch(ml.relay_url):
        p.append(_t("relay_url", where="[monitor_link]"))
    if not isinstance(ml.key_file, str):
        p.append(_t("path", where="[monitor_link]", name="key_file"))
    if ml.enabled is True and "monlink" not in modules.run:
        p.append(_t("module_not_run", where="[monitor_link]", module="monlink"))
    return p


_SERVER_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def _diffusion_problems(df: Diffusion, modules: Modules, sdr: Sdr) -> list[str]:
    from .diffusion.protocol import CODECS, STATION_NAME   # calculs purs, sans dépendance
    p = []
    for name in ("enabled", "tls", "outside_bands"):
        if not isinstance(getattr(df, name), bool):
            p.append(_t("bool", where="[diffusion]", name=name))
    if not isinstance(df.server, str) or (df.server and not _SERVER_NAME_RE.fullmatch(df.server)):
        p.append(_t("diffusion.server"))
    if not isinstance(df.station, str) or (df.station and not STATION_NAME.fullmatch(df.station)):
        p.append(_t("diffusion.station"))
    if df.codec not in CODECS:
        p.append(_t("diffusion.codec"))
    for name in ("source_port", "api_port", "audio_port"):
        v = getattr(df, name)
        low = 1024 if name == "audio_port" else 1
        if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= 65535:
            p.append(_t("int_range", where="[diffusion]", name=name, low=low, high=65535))
    if df.audio_port in (modules.bus_port, sdr.audio_port):
        p.append(_t("diffusion.audio_port_clash"))
    if not isinstance(df.key_file, str):
        p.append(_t("path", where="[diffusion]", name="key_file"))
    if df.tls is False and df.server not in ("127.0.0.1", "localhost"):
        p.append(_t("diffusion.tls_local"))
    if df.enabled is True:
        if "diffusion" not in modules.run:
            p.append(_t("module_not_run", where="[diffusion]", module="diffusion"))
        if not df.server or not df.station:
            p.append(_t("diffusion.incomplete"))
    return p


def diffusion_key_path(cfg: "Config", config_path: str | Path) -> Path:
    """Secrets de la diffusion : key_file (relatif = à côté de station.toml), sinon state_dir/diffusion/diffusion.key
    (0600). Jamais dans station.toml (cahier § 3)."""
    if cfg.diffusion.key_file:
        path = Path(cfg.diffusion.key_file)
        return path if path.is_absolute() else Path(config_path).parent / path
    return Path(cfg.supervisor.state_dir) / "diffusion" / "diffusion.key"


SSH_USER_RE = re.compile(r"[a-z_][a-z0-9_.-]{0,31}")


def _remote_console_problems(cfg: Config) -> list[str]:
    rc, p = cfg.remote_console, []
    if not isinstance(rc.enabled, bool):
        p.append(_t("bool", where="[remote_console]", name="enabled"))
    if not isinstance(rc.account, str) or (rc.account and not SSH_USER_RE.fullmatch(rc.account)):
        p.append(_t("remote_console.account", account=rc.account))
    if isinstance(rc.port, bool) or not isinstance(rc.port, int) or not 1024 <= rc.port <= 65535:
        p.append(_t("remote_console.port_range", port=rc.port))
    elif rc.port in (cfg.network.gateway_port, cfg.network.rigctld_port):
        p.append(_t("remote_console.port_taken", port=rc.port))
    if isinstance(rc.idle_min, bool) or not isinstance(rc.idle_min, int) or not 5 <= rc.idle_min <= 240:
        p.append(_t("remote_console.idle_min", idle=rc.idle_min))
    if rc.enabled is True:
        admins = [c.id for c in cfg.clients if c.admin is True and c.role == "operator" and c.password_hash]
        if not admins:
            p.append(_t("remote_console.no_admin"))
    return p


def _remote_console_compat(d: dict) -> dict:
    """[remote_console] des versions 0.176.0 et 0.177.0 (raccourci SSH) : ssh_user devient account, les ports SSH et
    du tunnel sont oubliés, et le service n'est PAS mis en marche sans un choix fait au menu 4.6."""
    rc = d.get("remote_console")
    if not isinstance(rc, dict) or not ({"ssh_user", "ssh_port", "web_port"} & set(rc)):
        return rc if isinstance(rc, dict) else {}
    rc = dict(rc)
    user = rc.pop("ssh_user", "")
    rc.pop("ssh_port", None)
    rc.pop("web_port", None)
    rc.setdefault("account", user)
    rc["enabled"] = False
    return rc


def monlink_key_path(cfg: Config, config_path: str | Path) -> Path:
    """Clés du monitoring : key_file (relatif = à côté de station.toml), sinon state_dir/monlink/monlink.key (écrit par
    le module lui-même, droits 0600). Jamais le fichier de la présence."""
    if cfg.monitor_link.key_file:
        path = Path(cfg.monitor_link.key_file)
        return path if path.is_absolute() else Path(config_path).parent / path
    return Path(cfg.supervisor.state_dir) / "monlink" / MONLINK_KEY_FILE


def presence_key_path(cfg: Config, config_path: str | Path) -> Path:
    """Clés de la station pour la présence : key_file (relatif = à côté de station.toml), sinon
    state_dir/presence/presence.key (écrit par le module lui-même, droits 0600)."""
    if cfg.presence.key_file:
        path = Path(cfg.presence.key_file)
        return path if path.is_absolute() else Path(config_path).parent / path
    return Path(cfg.supervisor.state_dir) / "presence" / PRESENCE_KEY_FILE


def breizh_key_path(cfg: Config, config_path: str | Path) -> Path:
    """Fichier de la clé d'appairage : key_file (relatif = à côté de station.toml), sinon breizh.key."""
    name = cfg.breizh.key_file or BREIZH_KEY_FILE
    path = Path(name)
    return path if path.is_absolute() else Path(config_path).parent / path


def is_loopback(host: str) -> bool:
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def exposure_problem(cfg: Config) -> str:
    """Texte du problème si l'API écoute hors de la machine sans chiffrement, sinon chaîne vide.

    La passerelle refuse alors de démarrer son API (elle reste en réception seule) : un mot de passe ne doit
    jamais circuler en clair sur un réseau. Seul `allow_insecure_http = true` (VPN qui chiffre déjà) le permet.
    """
    n = cfg.network
    if is_loopback(n.gateway_bind) or (n.tls_cert and n.tls_key) or n.allow_insecure_http:
        return ""
    return _t("network.exposure", bind=n.gateway_bind)


def warnings(cfg: Config) -> list[str]:
    """Points non bloquants mais à connaître."""
    w: list[str] = []
    if cfg.safety.enforce_bands and not cfg.bands:
        w.append(_t("warn.no_band"))
    if not cfg.safety.enforce_bands:
        w.append(_t("warn.bands_off"))
    if cfg.rig.model != DUMMY_MODEL:
        if not cfg.audio.capture_device or not cfg.audio.playback_device:
            w.append(_t("warn.no_audio"))
    problem = exposure_problem(cfg)
    if problem:
        w.append(problem)
    if cfg.spectrum.enabled and cfg.spectrum.source == "rigctld" and cfg.rig.port and not cfg.rig.speed:
        w.append(_t("warn.spectrum_speed", min_speed=SPECTRUM_MIN_SPEED))
    if any(c.token for c in cfg.clients):
        w.append(_t("warn.token"))
    if not cfg.clients:
        w.append(_t("warn.no_client"))
    if cfg.rig.model != DUMMY_MODEL and not cfg.supervisor.notify_url:
        w.append(_t("warn.no_notify"))
    if cfg.rig.ptt_type in ("RTS", "DTR"):
        w.append(_t("warn.ptt_rts_dtr"))
    return w


def _build(cls, data: dict, section: str, problems: list[str]):
    known = {f.name for f in fields(cls)}
    for key in sorted(set(data) - known):
        problems.append(_t("unknown_key", section=section, key=key))
    return cls(**{k: v for k, v in data.items() if k in known})


def _build_cluster(data: dict, problems: list[str]) -> Cluster:
    data = dict(data)
    sources = data.pop("source", [])
    if not isinstance(sources, list):
        problems.append(_t("cluster.sources_table"))
        sources = []
    cluster = _build(Cluster, data, "cluster", problems)
    cluster.source = [_build(ClusterSource, s, "cluster.source", problems) for s in sources]
    return cluster


def build(d: dict) -> tuple[Config, list[str]]:
    """Construit une Config SANS la refuser : retourne (config, problèmes). Les clés inconnues sont ignorées et signalées.

    Sert à reprendre une configuration incomplète (import depuis un autre PC, assistant relancé) comme base
    de départ. Une config qui sert à faire tourner la station passe TOUJOURS par `from_dict` / `load`.
    """
    problems: list[str] = []
    top_known = {"schema_version", "config_revision", "rig", "audio", "tools", "network",
                 "safety", "supervisor", "modules", "update", "spectrum", "cluster", "selcall", "access", "swr", "breizh",
                 "netprobe", "presence", "monitor_link", "diffusion", "remote_console", "freedv", "sdr", "bands", "clients"}
    for key in sorted(set(d) - top_known):
        problems.append(_t("unknown_root_key", key=key))
    try:
        cfg = Config(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            config_revision=d.get("config_revision", 1),
            rig=_build(Rig, d.get("rig", {}), "rig", problems),
            audio=_build(Audio, d.get("audio", {}), "audio", problems),
            tools=_build(Tools, d.get("tools", {}), "tools", problems),
            network=_build(Network, d.get("network", {}), "network", problems),
            safety=_build(Safety, d.get("safety", {}), "safety", problems),
            supervisor=_build(Supervisor, d.get("supervisor", {}), "supervisor", problems),
            modules=_build(Modules, d.get("modules", {}), "modules", problems),
            update=_build(Update, d.get("update", {}), "update", problems),
            spectrum=_build(Spectrum, d.get("spectrum", {}), "spectrum", problems),
            cluster=_build_cluster(d.get("cluster", {}), problems),
            selcall=_build(Selcall, d.get("selcall", {}), "selcall", problems),
            access=_build(Access, d.get("access", {}), "access", problems),
            swr=_build(Swr, d.get("swr", {}), "swr", problems),
            breizh=_build(Breizh, d.get("breizh", {}), "breizh", problems),
            netprobe=_build(Netprobe, d.get("netprobe", {}), "netprobe", problems),
            presence=_build(Presence, d.get("presence", {}), "presence", problems),
            monitor_link=_build(MonitorLink, d.get("monitor_link", {}), "monitor_link", problems),
            diffusion=_build(Diffusion, d.get("diffusion", {}), "diffusion", problems),
            remote_console=_build(RemoteConsole, _remote_console_compat(d), "remote_console", problems),
            freedv=_build(Freedv, d.get("freedv", {}), "freedv", problems),
            sdr=_build(Sdr, d.get("sdr", {}), "sdr", problems),
            bands=[_build(Band, b, "bands", problems) for b in d.get("bands", [])],
            clients=[_build(ClientAuth, c, "clients", problems) for c in d.get("clients", [])],
        )
    except TypeError as exc:  # champ obligatoire manquant (ex. Band sans nom)
        raise ConfigError(problems + [_t("bad_structure", error=exc)]) from exc
    return cfg, problems + validate(cfg)


def from_dict(d: dict) -> Config:
    cfg, problems = build(d)
    if problems:
        raise ConfigError(problems)
    return cfg


def _read_toml(path: str | Path) -> dict:
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([_t("toml_unreadable", error=exc)]) from exc


def load(path: str | Path) -> Config:
    return from_dict(_read_toml(path))


def load_unchecked(path: str | Path) -> tuple[Config, list[str]]:
    """Comme `load`, sans refuser une config incomplète : (config, problèmes). ConfigError si illisible."""
    return build(_read_toml(path))


def _s(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # chaîne TOML valide


def _list(values: list[str]) -> str:
    return f"[{', '.join(_s(v) for v in values)}]"


def _render_cluster(c: Cluster) -> list[str]:
    lines = [
        "[cluster]   # module Cluster DX : se règle avec TRX Console (menu 5.1) ou python -m trxstation.cluster.setup",
        f"enabled = {str(c.enabled).lower()}",
        f"call = {_s(c.call)}   # VOTRE indicatif radioamateur, seul envoyé aux clusters et au RBN",
        f"cb_call = {_s(c.cb_call)}   # votre indicatif de cibiste (sources CB)",
        f"modes = {_list(c.modes)}   # CW SSB AM FM FREEDV ; [] = tous ; le numérique (FT8...) est toujours écarté",
        f"bands = {_list(c.bands)}   # [] = toutes",
        f"continents = {_list(c.continents)}   # continent du spotteur, ex. [\"EU\"] ; [] = tous",
        f"blacklist = {_list(c.blacklist)}",
        f"ttl_min = {c.ttl_min}",
        f"rbn_ttl_min = {c.rbn_ttl_min}",
        f"cty_update = {str(c.cty_update).lower()}",
        "",
    ]
    for s in c.source:
        lines += ["[[cluster.source]]", f"name = {_s(s.name)}", f"type = {_s(s.type)}"]
        if s.type == "web":
            lines.append(f"url = {_s(s.url)}")
        else:
            lines += [f"host = {_s(s.host)}", f"port = {s.port}"]
        if s.call:
            lines.append(f"call = {_s(s.call)}")
        if s.secret:
            lines.append(f"secret = {_s(s.secret)}   # nom du mot de passe dans secrets.toml, jamais le mot de passe")
        lines += [f"priority = {s.priority}", f"enabled = {str(s.enabled).lower()}", ""]
    return lines


def render_toml(cfg: Config) -> str:
    r, a, n, s, v = cfg.rig, cfg.audio, cfg.network, cfg.safety, cfg.supervisor
    np = cfg.netprobe
    lines = [
        "# station.toml : source de vérité de la station (générée par trx-setup).",
        "# Les clés de [rig], [network], [bands], le plafond du TOT et [supervisor] ne se",
        "# modifient que sur le Pi. Le smartphone ne pourra changer que le reste.",
        f"schema_version = {cfg.schema_version}",
        f"config_revision = {cfg.config_revision}",
        "",
        "[rig]",
        f"model = {r.model}",
        f"port = {_s(r.port)}",
    ]
    if r.speed:
        lines.append(f"speed = {r.speed}")
    lines += [
        f"ptt_type = {_s(r.ptt_type)}   # RIG (CAT), RTS, DTR, GPIO, GPION, NONE",
        f"ptt_port = {_s(r.ptt_port)}",
        f"extra_conf = [{', '.join(_s(c) for c in r.extra_conf)}]",
        f"tx_modes = [{', '.join(_s(m) for m in r.tx_modes)}]   # ex. Icom : [\"PKTUSB\", \"PKTLSB\"] ; vide = pas de restriction",
        f"max_power_w = {r.max_power_w}   # puissance maximale du poste (ex. 100) : la page affiche des watts ; 0 = inconnue, des %",
        f"tuner = {'true' if r.tuner else 'false'}   # coupleur d'antenne du poste utilisé : réglages d'accord vérifiés à chaque connexion",
        "",
        "[audio]",
        f"capture_device = {_s(a.capture_device)}",
        f"playback_device = {_s(a.playback_device)}",
        f"sample_rate = {a.sample_rate}",
        f"rx_gain_db = {a.rx_gain_db}",
        f"tx_gain_db = {a.tx_gain_db}",
        "",
        "[tools]",
        f"hamlib_dir = {_s(cfg.tools.hamlib_dir)}   # Windows : dossier contenant bin\\rigctld.exe",
        "",
        "[network]",
        f"rigctld_host = {_s(n.rigctld_host)}   # doit rester local",
        f"rigctld_port = {n.rigctld_port}",
        f"gateway_bind = {_s(n.gateway_bind)}   # 127.0.0.1 = machine seule ; hors machine : TLS requis (docs/acces-distant.md)",
        f"gateway_port = {n.gateway_port}",
        f"web_client = {str(n.web_client).lower()}   # page web de contrôle sur le même port",
        f"tls_cert = {_s(n.tls_cert)}   # HTTPS natif (PEM) ; vide = pas de TLS (proxy HTTPS ou VPN devant)",
        f"tls_key = {_s(n.tls_key)}",
        f"allow_insecure_http = {str(n.allow_insecure_http).lower()}   # true : écoute réseau sans TLS (VPN uniquement)",
        f"trusted_proxies = [{', '.join(_s(x) for x in n.trusted_proxies)}]   # crus pour X-Forwarded-For",
        f"ice_servers = [{', '.join(_s(x) for x in n.ice_servers)}]   # [] : réseau local ou VPN seulement",
        "",
        "[safety]",
        f"tot_s = {s.tot_s}",
        f"tot_ceiling_s = {s.tot_ceiling_s}",
        f"enforce_bands = {str(s.enforce_bands).lower()}   # false : le poste interdit déjà l'émission hors bandes",
        f"warn_before_s = {s.warn_before_s}",
        f"heartbeat_interval_ms = {s.heartbeat_interval_ms}",
        f"heartbeat_timeout_ms = {s.heartbeat_timeout_ms}",
        f"rig_temp_warn_c = {s.rig_temp_warn_c}   # température du poste : avertissement (sans effet si le poste ne la donne pas)",
        f"rig_temp_cut_c = {s.rig_temp_cut_c}   # émission à distance coupée, reprise sous rig_temp_warn_c",
        f"allow_replay = {str(s.allow_replay).lower()}   # rediffusion d'un enregistrement de l'audio reçu (accordée par l'assistant, responsabilité de l'opérateur)",
        "",
        "[supervisor]",
        f"tot_abs_s = {v.tot_abs_s}",
        f"poll_interval_s = {v.poll_interval_s}",
        f"max_reboots_per_hour = {v.max_reboots_per_hour}",
        f"notify_url = {_s(v.notify_url)}",
        f"notify_lang = {_s(v.notify_lang)}   # langue des alertes : fr ou en",
        f"status_path = {_s(v.status_path)}",
        f"state_dir = {_s(v.state_dir)}",
        f"service_mode = {_s(v.service_mode)}   # auto | systemd | managed",
        f"instance_lock_port = {v.instance_lock_port}",
        f"stale_after_s = {v.stale_after_s}",
        f"startup_grace_s = {v.startup_grace_s}",
        f"mismatch_grace_s = {v.mismatch_grace_s}",
        f"rigctld_fail_s = {v.rigctld_fail_s}",
        f"recovery_wait_s = {v.recovery_wait_s}",
        f"healthy_reset_s = {v.healthy_reset_s}",
        f"temp_alert_c = {v.temp_alert_c}",
        f"mem_alert_pct = {v.mem_alert_pct}   # mémoire utilisée (%) : alerte ntfy seule ; 0 = aucune",
        f"disk_alert_pct = {v.disk_alert_pct}   # disque utilisé (%), dossier d'état et / : alerte ntfy seule ; 0 = aucune",
        f"alive_every_h = {v.alive_every_h}   # message « Station en service » sans sonnerie par notify_url ; 0 = aucun",
        f"allow_local_tx = {str(v.allow_local_tx).lower()}   # true : station partagée, l'émission au micro du poste n'est coupée que par tot_abs_s",
        f"local_tx_max_s = {v.local_tx_max_s}   # station partagée, opérateur présent (action sur le poste) : émission locale tolérée jusque-là (600 au plus)",
        f"gateway_unit = {_s(v.gateway_unit)}",
        f"rigctld_unit = {_s(v.rigctld_unit)}",
        "",
        "[modules]",
        f"run = [{', '.join(_s(x) for x in cfg.modules.run)}]   # modules à faire tourner, ex. [\"demo\"] ; [] = aucun",
        f"bus_port = {cfg.modules.bus_port}   # API interne, écoute en 127.0.0.1 seulement",
        f"run_as = {_s(cfg.modules.run_as)}   # Linux : compte des modules quand le superviseur est root (jamais root)",
        f"extra_dir = {_s(cfg.modules.extra_dir)}   # modules supplémentaires ; vide = modules fournis seulement",
        "",
        "[update]",
        f"enabled = {str(cfg.update.enabled).lower()}   # cherche une nouvelle version sur GitHub (installation après confirmation seulement)",
        f"allow_prerelease = {str(cfg.update.allow_prerelease).lower()}   # true : propose aussi les pré-versions",
        "",
        "[spectrum]",
        f"enabled = {str(cfg.spectrum.enabled).lower()}   # spectre HF du poste (waterfall HF) ; false = un seul port, comme avant",
        f"source = {_s(cfg.spectrum.source)}   # civ_port : second port CI-V du poste (Icom) ; rigctld : Hamlib 4.6+ async",
        f"port = {_s(cfg.spectrum.port)}   # civ_port : second port du poste (jamais le port CAT) ; trx-setup --spectre PORT",
        f"civ_address = {_s(cfg.spectrum.civ_address)}   # civ_port : adresse CI-V du poste (hexadécimal), revérifiée à chaque ouverture",
        f"baud = {cfg.spectrum.baud}   # civ_port : débit du second port",
        f"data_port = {cfg.spectrum.data_port}   # rigctld : UDP sur 127.0.0.1",
        f"max_fps = {cfg.spectrum.max_fps}   # images par seconde envoyées aux clients (1 à 20)",
        "",
        *_render_cluster(cfg.cluster),
        "[selcall]   # squelch numérique par appel de groupe (docs/selcall-cahier-des-charges.md)",
        f"enabled = {str(cfg.selcall.enabled).lower()}   # fonction disponible sur cette station",
        f"send_on_tx_end = {str(cfg.selcall.send_on_tx_end).lower()}   # trame émise en fin d'émission, à la place du roger bip",
        f"manual_repeat = {cfg.selcall.manual_repeat}   # appel manuel : nombre d'émissions de la trame (1 à 5)",
        f"manual_gap_ms = {cfg.selcall.manual_gap_ms}",
        f"filter_mode = {_s(cfg.selcall.filter_mode)}   # tonalités dans l'audio reçu : mute | attenuate | chime",
        f"attenuation_db = {cfg.selcall.attenuation_db}",
        f"audio_delay_ms = {cfg.selcall.audio_delay_ms}   # retard de l'audio reçu (250 à 1 000 ms)",
        f"tx_level_dbfs = {cfg.selcall.tx_level_dbfs}   # niveau de la trame émise (sous le seuil d'ALC)",
        f"notify_on_call = {str(cfg.selcall.notify_on_call).lower()}   # notification ntfy à l'ouverture",
        f"history_size = {cfg.selcall.history_size}",
        "",
        "# Bandes où l'émission est autorisée si enforce_bands = true. Liste vide = réception seule.",
        "# À vérifier et adapter à ta licence et à ton pays.",
    ]
    ac = cfg.access
    lines += [
        "[access]   # visiteurs en réception seule (docs/visiteurs-cahier-des-charges.md) ; relu sans redémarrer",
        f"max_listeners = {ac.max_listeners}   # visiteurs connectés en même temps ; 0 = fonction désactivée",
        f"max_operators = {ac.max_operators}   # connexions opérateur (quota à part, jamais pris par un visiteur)",
        f"listeners_need_operator = {str(ac.listeners_need_operator).lower()}   # true : visiteurs admis seulement si un opérateur est connecté",
        f"operator_grace_s = {ac.operator_grace_s}   # opérateur perdu : attente avant de déconnecter les visiteurs (0 à 600 s)",
        f"listeners_outside_bands = {str(ac.listeners_outside_bands).lower()}   # false : silence pour les visiteurs hors [[bands]]",
        f"listener_spectrum_fps = {ac.listener_spectrum_fps}   # spectre HF des visiteurs : images par seconde au plus (1 à 20)",
        "# Surcharge : au-delà pendant 10 s, visiteurs déconnectés ; réouverture après 5 min nettement en dessous",
        f"overload_temp_c = {ac.overload_temp_c}   # température du processeur (°C)",
        f"overload_cpu_pct = {ac.overload_cpu_pct}   # charge de tous les cœurs (%)",
        f"overload_lag_ms = {ac.overload_lag_ms}   # retard de la boucle de la passerelle (ms)",
        f"overload_mem_pct = {ac.overload_mem_pct}   # mémoire libre minimale (%)",
        "",
        "[swr]   # mesure de TOS de l'antenne (docs/tos-cahier-des-charges.md) ; réglages de la station seulement",
        f"enabled = {str(cfg.swr.enabled).lower()}   # false : mesure absente",
        f"max_power_pct = {cfg.swr.max_power_pct}   # plafond de puissance, % de la puissance du poste (5 à 50)",
        f"max_points = {cfg.swr.max_points}   # points d'une mesure au plus (2 à 200)",
        f"point_tx_max_s = {cfg.swr.point_tx_max_s}   # émission d'un point au plus, en secondes (0.5 à 3)",
        "",
        "[breizh]   # Breizh Audio Box dans la chaîne d'émission (docs/breizh-cahier-des-charges.md) ; le micro circule EN CLAIR sur le réseau local",
        f"enabled = {str(cfg.breizh.enabled).lower()}",
        f"host = {_s(cfg.breizh.host)}   # adresse IP PRIVÉE du PC de Breizh",
        f"port = {cfg.breizh.port}   # port UDP de Breizh (1024 à 65535)",
        f"key_file = {_s(cfg.breizh.key_file)}   # clé d'appairage ; vide = {BREIZH_KEY_FILE} à côté de ce fichier",
        f"block_timeout_ms = {cfg.breizh.block_timeout_ms}   # bloc pas revenu à temps : part sans traitement (15 à 100 ms)",
        f"lost_ms = {cfg.breizh.lost_ms}   # sans retour pendant ce délai : repli en direct (50 à 500 ms, > block_timeout_ms)",
        f"fallback_gain_db = {cfg.breizh.fallback_gain_db}   # gain du son direct en repli (-20 à 0 dB)",
        f"reactivate_after_s = {cfg.breizh.reactivate_after_s}   # stabilité avant le retour automatique (0 = à la main, 30 à 3600 s)",
        "",
        "[netprobe]   # sonde de qualité réseau (docs/netprobe-cahier-des-charges.md) : mesure et affiche, n'agit jamais sur l'émission",
        f"enabled = {str(np.enabled).lower()}",
        f"heartbeat_interval_s = {np.heartbeat_interval_s}   # battement réseau (0.5 à 10 s)",
        f"outage_missed_beats = {np.outage_missed_beats}   # battements sans écho = coupure (2 à 20)",
        f"lan_target = {_s(np.lan_target)}   # box à sonder ; auto = passerelle par défaut",
        f'internet_target = {_s(np.internet_target)}   # cible Internet ; "" = aucune',
        "# Seuils de DÉPART de l'indicateur ; ceux choisis dans la page ou l'application (statistiques) priment",
        f"loss_warn_pct = {np.loss_warn_pct}   # perte sur 60 s : orange (%)",
        f"loss_alert_pct = {np.loss_alert_pct}   # perte sur 60 s : rouge (%)",
        f"rtt_warn_ms = {np.rtt_warn_ms}   # aller-retour p95 sur 60 s : orange (ms)",
        f"rtt_alert_ms = {np.rtt_alert_ms}   # aller-retour p95 sur 60 s : rouge (ms)",
        f"alert_outage_s = {np.alert_outage_s}   # coupure plus longue : alerte par notify_url (0 = aucune)",
        f"alert_cooldown_s = {np.alert_cooldown_s}   # délai minimal entre deux alertes de la sonde (s)",
        f"log_retention_days = {np.log_retention_days}   # résumés de 10 s (1 à 30 jours)",
        f"stats_retention_days = {np.stats_retention_days}   # coupures et statistiques (7 à 90 jours)",
        f"vpn_shared_warn = {str(np.vpn_shared_warn).lower()}   # avertir quand deux appareils semblent partager un profil VPN",
        f"rsrp_warn_dbm = {np.rsrp_warn_dbm}   # signal 4G/5G de l'application : orange (dBm)",
        f"rsrp_alert_dbm = {np.rsrp_alert_dbm}   # rouge (dBm)",
        f"sinr_warn_db = {np.sinr_warn_db}   # rapport signal/bruit : orange (dB)",
        f"sinr_alert_db = {np.sinr_alert_db}   # rouge (dB)",
        "",
        "[presence]   # présence de groupe (docs/presence-cahier-des-charges.md) : module « presence » de [modules] run",
        f"enabled = {str(cfg.presence.enabled).lower()}",
        f"relay_url = {_s(cfg.presence.relay_url)}   # relais (https:// ; http:// seulement vers 127.0.0.1)",
        f"key_file = {_s(cfg.presence.key_file)}   # clés de la station ; vide = state_dir/presence/{PRESENCE_KEY_FILE}",
        "",
        "[monitor_link]   # monitoring inter-stations, assistance à distance (docs/cdc-monitoring.md § 17) : module « monlink »",
        f"enabled = {str(cfg.monitor_link.enabled).lower()}",
        f"relay_url = {_s(cfg.monitor_link.relay_url)}   # même relais que la présence (https://)",
        f"key_file = {_s(cfg.monitor_link.key_file)}   # clés du monitoring ; vide = state_dir/monlink/{MONLINK_KEY_FILE}",
        "",
        "[diffusion]   # diffusion en direct vers des internautes (docs/diffusion-cahier-des-charges.md) : module « diffusion »",
        f"enabled = {str(cfg.diffusion.enabled).lower()}",
        f"server = {_s(cfg.diffusion.server)}   # serveur de diffusion (aucun par défaut)",
        f"station = {_s(cfg.diffusion.station)}   # nom de la station sur ce serveur (a-z 0-9 -)",
        f"source_port = {cfg.diffusion.source_port}   # port TLS des sources (Icecast)",
        f"api_port = {cfg.diffusion.api_port}   # HTTPS des métadonnées",
        f"codec = {_s(cfg.diffusion.codec)}   # opus ou mp3",
        f"audio_port = {cfg.diffusion.audio_port}   # son de la passerelle vers le module (UDP, 127.0.0.1 seulement)",
        f"key_file = {_s(cfg.diffusion.key_file)}   # secrets ; vide = state_dir/diffusion/diffusion.key (0600)",
        f"tls = {str(cfg.diffusion.tls).lower()}   # false seulement vers 127.0.0.1 (faux serveur d'essai)",
        f"outside_bands = {str(cfg.diffusion.outside_bands).lower()}   # false : silence hors des [[bands]] ; true : tout diffuser",
        "",
        "[remote_console]   # TRX Console sur le réseau (HTTPS, comptes opérateurs admin = true) : menu 4.6",
        f"enabled = {str(cfg.remote_console.enabled).lower()}",
        f"account = {_s(cfg.remote_console.account)}   # compte Linux de la console (jamais root) ; vide sous Windows",
        f"port = {cfg.remote_console.port}   # https://<station>:{cfg.remote_console.port}/",
        f"idle_min = {cfg.remote_console.idle_min}   # session fermée après ce temps sans action (minutes)",
        "",
        "[freedv]   # FreeDV RADE V1 en réception : décodeurs freedv-ka9q et radae_rx (le mode se choisit depuis la page)",
        f"enabled = {str(cfg.freedv.enabled).lower()}",
        f"ka9q_path = {_s(cfg.freedv.ka9q_path)}   # nom seul = cherché dans le PATH",
        f"radae_rx_path = {_s(cfg.freedv.radae_rx_path)}",
        f"locator = {_s(cfg.freedv.locator)}   # locator de la station (JN18du) : distances de la liste « Activité FreeDV »",
        "",
        "[sdr]   # récepteur SDR en parallèle du TRX (réception seule) : module « sdr » de [modules] run",
        f"enabled = {str(cfg.sdr.enabled).lower()}",
        f"driver = {_s(cfg.sdr.driver)}   # sdrplay (API du fabricant, installée à la main) ou rtlsdr (clé RTL-SDR)",
        f"serial = {_s(cfg.sdr.serial)}   # numéro de série du SDR de cette station (trx-sdr --list)",
        f"core_path = {_s(cfg.sdr.core_path)}   # vide = sdr-core installé avec la station",
        f"sample_rate_hz = {cfg.sdr.sample_rate_hz}   # largeur : SDRplay 2000000 / 6000000 / 8000000 ; RTL-SDR 1024000 / 2048000 / 2400000",
        f"center_hz = {cfg.sdr.center_hz}   # fréquence centrale au démarrage",
        f"antenna = {_s(cfg.sdr.antenna)}   # entrée A ou B (RSP2 ; sans effet sur une clé RTL-SDR)",
        f"lna_state = {cfg.sdr.lna_state}   # 0 = gain maximal (0 à 8)",
        f"gain_reduction_db = {cfg.sdr.gain_reduction_db}   # réduction de gain FI (20 à 59 dB), AGC coupé",
        f"agc = {str(cfg.sdr.agc).lower()}   # AGC de la FI : le SDR règle lui-même la réduction de gain",
        f"audio_port = {cfg.sdr.audio_port}   # son du module vers la passerelle (UDP, 127.0.0.1 seulement)",
        f"fft_size = {cfg.sdr.fft_size}",
        f"bins = {cfg.sdr.bins}   # cases d'une ligne envoyée aux clients",
        f"lines_per_s = {cfg.sdr.lines_per_s}",
        f"max_cpu_pct = {cfg.sdr.max_cpu_pct}   # plafond du module, % d'un cœur : au-delà il se bride lui-même",
        f"max_mem_mb = {cfg.sdr.max_mem_mb}   # plafond de mémoire du module (Mo)",
        "",
    ]
    for client in cfg.clients:
        lines += ["[[clients]]", f"id = {_s(client.id)}"]
        if client.password_hash:
            lines.append(f"password_hash = {_s(client.password_hash)}")
        if client.token:
            lines.append(f"token = {_s(client.token)}   # ancien secret en clair : à remplacer")
        if client.role != "operator":
            lines.append(f"role = {_s(client.role)}   # visiteur : réception seule")
        if client.pseudo:
            lines.append(f"pseudo = {_s(client.pseudo)}")
        if client.enabled is not True:
            lines.append("enabled = false")
        if client.expires:
            lines.append(f"expires = {_s(client.expires)}")
        if client.admin is True:
            lines.append("admin = true   # peut ouvrir TRX Console sur le réseau")
        lines.append("")
    for b in cfg.bands:
        lines += ["[[bands]]", f"name = {_s(b.name)}", f"low_mhz = {b.low_mhz}",
                  f"high_mhz = {b.high_mhz}", ""]
    return "\n".join(lines).rstrip() + "\n"
