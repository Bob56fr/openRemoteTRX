# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Chargement, validation et écriture de station.toml (stdlib uniquement).

Principe de conception : en cas de doute, on refuse d'émettre.
  - une liste de bandes vide signifie « émission interdite » ;
  - toute incohérence entre les temporisations de sécurité est une erreur bloquante.
"""
from __future__ import annotations

import ipaddress
import json
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .passwords import is_valid_hash
from .paths import default_state_dir, default_status_path

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
        return args


@dataclass
class Audio:
    capture_device: str = ""       # audio reçu du TRX (ex. plughw:CARD=CODEC,DEV=0)
    playback_device: str = ""      # audio injecté vers le TRX
    sample_rate: int = 48000       # seul 48000 est géré (Opus)
    rx_gain_db: float = 0.0        # gain appliqué au son reçu
    tx_gain_db: float = 0.0        # gain appliqué au son émis (prudence : un excès sature l'émetteur)


@dataclass
class ClientAuth:
    id: str = ""                   # identifiant de connexion (ex. phone, car)
    token: str = ""                # ANCIEN secret en clair (16 caractères au moins) : accepté, mais à remplacer
    password_hash: str = ""        # empreinte scrypt du mot de passe (trx-setup --add-client / --set-password)


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


TEMP_MIN_C, TEMP_MAX_C = 20, 90      # bornes des seuils de température du poste


@dataclass
class Supervisor:
    tot_abs_s: int = 135              # TOT absolu, strictement > plafond de la passerelle
    poll_interval_s: float = 1.0      # cadence au repos (0,25 s pendant une émission)
    max_reboots_per_hour: int = 3     # au-delà : mode sûr (RX, passerelle arrêtée)
    notify_url: str = ""              # ex. https://ntfy.sh/mon-sujet (optionnel)
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
    temp_alert_c: float = 80.0        # alerte seule
    allow_local_tx: bool = True       # True (« station partagée ») : l'émission locale (micro du poste) n'est pas coupée,
                                      # sauf par tot_abs_s ; False : coupée à chaque passage (jamais d'escalade si « T 0 » marche)
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
    notify_on_call: bool = True       # notification ntfy du superviseur à l'ouverture
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
            p.append(f"[cluster] {name} doit valoir true ou false")
    for key, values, allowed in (("modes", c.modes, MODES), ("bands", c.bands, BAND_NAMES),
                                 ("continents", c.continents, CONTINENTS)):
        if not isinstance(values, list) or any(v not in allowed for v in values):
            p.append(f"[cluster] {key} : valeurs possibles {' '.join(allowed)} (numérique exclu)")
    if not isinstance(c.blacklist, list) or any(not isinstance(b, str) or not re.fullmatch(r"[A-Z0-9/]{1,15}\*?", b)
                                                for b in c.blacklist):
        p.append("[cluster] blacklist : indicatifs en majuscules, « XX* » pour un préfixe")
    if c.cb_call and own_call_problem(c.cb_call):
        p.append(f"[cluster] cb_call : {own_call_problem(c.cb_call)}")
    for key in ("ttl_min", "rbn_ttl_min"):
        v = getattr(c, key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 1 <= v <= 120:
            p.append(f"[cluster] {key} : de 1 à 120 minutes")
    names: set[str] = set()
    for s in c.source:
        label = f"[[cluster.source]] « {s.name} »"
        if not isinstance(s.name, str) or not _CLUSTER_NAME_RE.fullmatch(s.name):
            p.append(f"[[cluster.source]] name {s.name!r} : lettres, chiffres, - et _ (32 au plus)")
        elif s.name in names:
            p.append(f"{label} : nom en double")
        names.add(s.name)
        if s.type not in CLUSTER_SOURCE_TYPES:
            p.append(f"{label} : type {' ou '.join(CLUSTER_SOURCE_TYPES)} attendu")
        elif s.type == "web":
            if not isinstance(s.url, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s\"']*)?", s.url):
                p.append(f"{label} : url https://… attendue")
        else:
            if not isinstance(s.host, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", s.host or ""):
                p.append(f"{label} : host (nom ou adresse du serveur) attendu")
            if isinstance(s.port, bool) or not isinstance(s.port, int) or not 1 <= s.port <= 65535:
                p.append(f"{label} : port de 1 à 65535")
        if s.call and own_call_problem(s.call):
            p.append(f"{label} : call : {own_call_problem(s.call)}")
        if s.secret and (not isinstance(s.secret, str) or not _CLUSTER_NAME_RE.fullmatch(s.secret)):
            p.append(f"{label} : secret = NOM du mot de passe dans secrets.toml (lettres, chiffres, - et _)")
        if not isinstance(s.enabled, bool):
            p.append(f"{label} : enabled doit valoir true ou false")
        if isinstance(s.priority, bool) or not isinstance(s.priority, int) or not 1 <= s.priority <= 99:
            p.append(f"{label} : priority de 1 à 99")
    if c.enabled is True:
        active = [s for s in c.source if s.enabled is True]
        if not active:
            p.append("[cluster] activé sans aucune source active")
        if any(s.type != "web" and not s.call for s in active) and own_call_problem(c.call):
            p.append("[cluster] call : VOTRE indicatif est obligatoire pour se connecter aux clusters et au RBN "
                     f"({own_call_problem(c.call)})")
        if "cluster" not in modules.run:
            p.append("[cluster] activé mais « cluster » absent de [modules] run : le module ne serait jamais lancé")
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
        p.append(f"schema_version {cfg.schema_version} non supporté (attendu : {SCHEMA_VERSION})")

    r = cfg.rig
    if not isinstance(r.model, int) or r.model <= 0:
        p.append("[rig] model : numéro Hamlib requis (voir `rigctl -l`)")
    elif r.model != DUMMY_MODEL and not r.port:
        p.append("[rig] port : requis pour un vrai poste")
    if not 0 <= r.max_power_w <= 2000:
        p.append("[rig] max_power_w doit être compris entre 0 et 2000 (0 = inconnue)")
    for mode in r.tx_modes:
        if not re.fullmatch(r"[A-Za-z0-9\-]{1,16}", mode):
            p.append(f"[rig] tx_modes : « {mode} » n'est pas un nom de mode valide")
    if r.ptt_type not in PTT_TYPES:
        p.append(f"[rig] ptt_type '{r.ptt_type}' invalide (choix : {', '.join(PTT_TYPES)})")
    if r.speed is not None and r.speed <= 0:
        p.append("[rig] speed doit être positif")

    if cfg.audio.sample_rate != 48000:
        p.append("[audio] sample_rate : seul 48000 est géré")
    for name in ("rx_gain_db", "tx_gain_db"):
        if not -40 <= getattr(cfg.audio, name) <= 20:
            p.append(f"[audio] {name} doit rester entre -40 et +20 dB")
    seen: set[str] = set()
    for client in cfg.clients:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", client.id):
            p.append(f"[[clients]] identifiant invalide : {client.id!r} (lettres, chiffres, _ et -, 32 max)")
        elif client.id in seen:
            p.append(f"[[clients]] identifiant en double : {client.id}")
        seen.add(client.id)
        if bool(client.password_hash) == bool(client.token):
            p.append(f"[[clients]] {client.id} : il faut exactement un secret (password_hash, ou à défaut token)")
        elif client.password_hash and not is_valid_hash(client.password_hash):
            p.append(f"[[clients]] {client.id} : password_hash invalide (refais trx-setup --set-password {client.id})")
        elif client.token and len(client.token) < 16:
            p.append(f"[[clients]] {client.id} : jeton trop court (16 caractères minimum)")
    if bool(cfg.network.tls_cert) != bool(cfg.network.tls_key):
        p.append("[network] tls_cert et tls_key vont ensemble")
    for proxy in cfg.network.trusted_proxies:
        try:
            ipaddress.ip_network(proxy, strict=False)
        except ValueError:
            p.append(f"[network] trusted_proxies : « {proxy} » n'est pas une adresse IP ou un réseau CIDR")
    for server in cfg.network.ice_servers:
        if not re.fullmatch(r"(stun|turn)s?:[^\s]+", server):
            p.append(f"[network] ice_servers : « {server} » doit commencer par stun: ou turn:")

    n = cfg.network
    if n.rigctld_host not in ("127.0.0.1", "localhost", "::1"):
        p.append("[network] rigctld_host doit rester local : rigctld n'a aucune authentification")
    for name, port in (("rigctld_port", n.rigctld_port), ("gateway_port", n.gateway_port)):
        if not 1 <= port <= 65535:
            p.append(f"[network] {name} hors plage")

    s = cfg.safety
    if not 0 < s.tot_s <= s.tot_ceiling_s:
        p.append("[safety] il faut 0 < tot_s <= tot_ceiling_s")
    if not 0 < s.warn_before_s < s.tot_s:
        p.append("[safety] warn_before_s doit être entre 0 et tot_s")
    if s.heartbeat_interval_ms <= 0 or s.heartbeat_timeout_ms < 2 * s.heartbeat_interval_ms:
        p.append("[safety] heartbeat_timeout_ms doit valoir au moins 2x heartbeat_interval_ms")
    if not TEMP_MIN_C <= s.rig_temp_warn_c < s.rig_temp_cut_c <= TEMP_MAX_C:
        p.append(f"[safety] il faut {TEMP_MIN_C} <= rig_temp_warn_c < rig_temp_cut_c <= {TEMP_MAX_C} (°C)")

    v = cfg.supervisor
    if v.tot_abs_s <= s.tot_ceiling_s:
        p.append("[supervisor] tot_abs_s doit être strictement supérieur à safety.tot_ceiling_s")
    if v.max_reboots_per_hour < 0:
        p.append("[supervisor] max_reboots_per_hour ne peut pas être négatif")
    if v.stale_after_s < 0.5:
        p.append("[supervisor] stale_after_s doit valoir au moins 0,5 s (la passerelle écrit toutes les 0,25 s)")
    for name in ("poll_interval_s", "recovery_wait_s", "healthy_reset_s", "rigctld_fail_s", "temp_alert_c"):
        if getattr(v, name) <= 0:
            p.append(f"[supervisor] {name} doit être positif")
    for name in ("startup_grace_s", "mismatch_grace_s"):
        if getattr(v, name) < 0:
            p.append(f"[supervisor] {name} ne peut pas être négatif")
    if v.service_mode not in ("auto", "systemd", "managed"):
        p.append("[supervisor] service_mode doit valoir auto, systemd ou managed")
    if not 1 <= v.instance_lock_port <= 65535:
        p.append("[supervisor] instance_lock_port hors plage")
    if not v.status_path or not v.state_dir:
        p.append("[supervisor] status_path et state_dir sont requis")
    if v.notify_url and not v.notify_url.startswith(("https://", "http://")):
        p.append("[supervisor] notify_url doit commencer par http:// ou https://")

    m = cfg.modules
    for name in m.run:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", name):
            p.append(f"[modules] run : « {name} » n'est pas un nom de module valide")
    if len(set(m.run)) != len(m.run):
        p.append("[modules] run : un module est cité deux fois")
    if not 1024 <= m.bus_port <= 65535:
        p.append("[modules] bus_port hors plage (1024 à 65535)")
    elif m.bus_port in (n.gateway_port, n.rigctld_port, v.instance_lock_port):
        p.append("[modules] bus_port doit différer de gateway_port, rigctld_port et instance_lock_port")
    if m.run_as and not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", m.run_as):
        p.append(f"[modules] run_as : « {m.run_as} » n'est pas un nom de compte valide")
    elif m.run_as == "root":
        p.append("[modules] run_as : un module ne doit jamais tourner en root")

    for name in ("enabled", "allow_prerelease"):
        if not isinstance(getattr(cfg.update, name), bool):
            p.append(f"[update] {name} doit valoir true ou false")

    sc = cfg.selcall
    for name in ("enabled", "send_on_tx_end", "notify_on_call"):
        if not isinstance(getattr(sc, name), bool):
            p.append(f"[selcall] {name} doit valoir true ou false")
    ranges = {"manual_repeat": (1, 5), "manual_gap_ms": (200, 3000), "attenuation_db": (6, 60),
              "audio_delay_ms": (250, 1000), "history_size": (1, 50)}
    for name, (lo, hi) in ranges.items():
        v = getattr(sc, name)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            p.append(f"[selcall] {name} : entier de {lo} à {hi} attendu")
    if sc.filter_mode not in SELCALL_FILTER_MODES:
        p.append(f"[selcall] filter_mode : {' | '.join(SELCALL_FILTER_MODES)} attendu")
    if not isinstance(sc.tx_level_dbfs, (int, float)) or isinstance(sc.tx_level_dbfs, bool) or not -30 <= sc.tx_level_dbfs <= -1:
        p.append("[selcall] tx_level_dbfs : de -30 à -1 dBFS (sous le seuil d'ALC)")

    sp = cfg.spectrum
    reserved = sorted(set(_conf_keys(r.extra_conf)) & set(RESERVED_RIGCTLD_CONF))
    if reserved:
        p.append(f"[rig] extra_conf : {', '.join(reserved)} interdit(s) ici (réglé par [spectrum] ; le serveur de "
                 "commandes UDP de Hamlib n'a aucune authentification)")
    if not isinstance(sp.enabled, bool):
        p.append("[spectrum] enabled doit valoir true ou false")
    if isinstance(sp.data_port, bool) or not isinstance(sp.data_port, int) or not 1024 <= sp.data_port <= 65535:
        p.append("[spectrum] data_port hors plage (1024 à 65535)")
    if isinstance(sp.max_fps, bool) or not isinstance(sp.max_fps, int) or not 1 <= sp.max_fps <= 20:
        p.append("[spectrum] max_fps : de 1 à 20 images par seconde")
    if sp.source not in SPECTRUM_SOURCES:
        p.append(f"[spectrum] source : {' ou '.join(SPECTRUM_SOURCES)} attendu")
    if sp.enabled is True and sp.source == "civ_port":
        same = {x.strip().lower() for x in (r.port, r.ptt_port) if x and x.strip()}
        if not isinstance(sp.port, str) or not sp.port.strip():
            p.append("[spectrum] port : second port du poste à indiquer (ex. COM7), ou enabled = false")
        elif sp.port.strip().lower() in same:
            p.append(f"[spectrum] port {sp.port} : c'est le port CAT ou PTT du poste ; il faut le SECOND port, réglé en CI-V")
        if not isinstance(sp.civ_address, str) or parse_civ_address(sp.civ_address) is None:
            p.append("[spectrum] civ_address : adresse CI-V du poste en hexadécimal, de 01 à DF (ex. B6)")
        if sp.baud not in CIV_BAUDS:
            p.append(f"[spectrum] baud : {', '.join(map(str, CIV_BAUDS))}")
        if not is_icom_model(r.model):
            p.append("[spectrum] source civ_port : postes Icom seulement (modèle Hamlib 3xxx)")
    if sp.enabled is True and sp.source == "rigctld" and r.speed and r.speed < SPECTRUM_MIN_SPEED:
        p.append(f"[spectrum] le spectre exige [rig] speed = {SPECTRUM_MIN_SPEED} au moins (débit actuel {r.speed}) : "
                 "à un débit plus bas, il saturerait la liaison et retarderait les ordres du PTT")

    for b in cfg.bands:
        if not 0 < b.low_mhz < b.high_mhz:
            p.append(f"[[bands]] '{b.name}' : bornes invalides")
    p += validate_cluster(cfg.cluster, cfg.modules)
    return p


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
    return (f"L'API écouterait sur {n.gateway_bind} SANS chiffrement : mots de passe en clair sur le réseau. "
            "Configure tls_cert/tls_key, mets un proxy HTTPS devant (gateway_bind = 127.0.0.1), ou, si le trafic est déjà "
            "chiffré par un VPN, allow_insecure_http = true.")


def warnings(cfg: Config) -> list[str]:
    """Points non bloquants mais à connaître."""
    w: list[str] = []
    if cfg.safety.enforce_bands and not cfg.bands:
        w.append("Aucune bande autorisée : l'émission sera IMPOSSIBLE (réception seule).")
    if not cfg.safety.enforce_bands:
        w.append("Contrôle des bandes DÉSACTIVÉ : seul le poste empêche d'émettre hors des bandes (vérifie son réglage, "
                 "p. ex. « TX limit » sur un Icom).")
    if cfg.rig.model != DUMMY_MODEL:
        if not cfg.audio.capture_device or not cfg.audio.playback_device:
            w.append("Périphériques audio non définis : pas d'audio tant qu'ils ne sont pas renseignés.")
    problem = exposure_problem(cfg)
    if problem:
        w.append(problem)
    if cfg.spectrum.enabled and cfg.spectrum.source == "rigctld" and cfg.rig.port and not cfg.rig.speed:
        w.append(f"[spectrum] activé avec le débit par défaut de Hamlib : indique [rig] speed = {SPECTRUM_MIN_SPEED} "
                 "(et le même débit CI-V dans le menu du poste).")
    if any(c.token for c in cfg.clients):
        w.append("Des clients utilisent encore un jeton en clair : remplace-le par un mot de passe haché "
                 "(trx-setup --set-password NOM).")
    if not cfg.clients:
        w.append("Aucun client autorisé ([[clients]]) : aucun accès distant (trx-setup --add-client NOM).")
    if cfg.rig.model != DUMMY_MODEL and not cfg.supervisor.notify_url:
        w.append("Aucune URL d'alerte (notify_url) : les récupérations du superviseur ne seront pas notifiées.")
    if cfg.rig.ptt_type in ("RTS", "DTR"):
        w.append("PTT par RTS/DTR : vérifie que l'ouverture du port ne déclenche pas une émission "
                 "brève au démarrage ou au reset USB.")
    return w


def _build(cls, data: dict, section: str, problems: list[str]):
    known = {f.name for f in fields(cls)}
    for key in sorted(set(data) - known):
        problems.append(f"[{section}] clé inconnue : {key}")
    return cls(**{k: v for k, v in data.items() if k in known})


def _build_cluster(data: dict, problems: list[str]) -> Cluster:
    data = dict(data)
    sources = data.pop("source", [])
    if not isinstance(sources, list):
        problems.append("[[cluster.source]] : tableau de sources attendu")
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
                 "safety", "supervisor", "modules", "update", "spectrum", "cluster", "selcall", "bands", "clients"}
    for key in sorted(set(d) - top_known):
        problems.append(f"clé inconnue à la racine : {key}")
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
            bands=[_build(Band, b, "bands", problems) for b in d.get("bands", [])],
            clients=[_build(ClientAuth, c, "clients", problems) for c in d.get("clients", [])],
        )
    except TypeError as exc:  # champ obligatoire manquant (ex. Band sans nom)
        raise ConfigError(problems + [f"structure invalide : {exc}"]) from exc
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
        raise ConfigError([f"TOML illisible : {exc}"]) from exc


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
        "[cluster]   # module Cluster DX : se règle avec TRX Console (menu 12) ou python -m trxstation.cluster.setup",
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
        "",
        "[supervisor]",
        f"tot_abs_s = {v.tot_abs_s}",
        f"poll_interval_s = {v.poll_interval_s}",
        f"max_reboots_per_hour = {v.max_reboots_per_hour}",
        f"notify_url = {_s(v.notify_url)}",
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
        f"allow_local_tx = {str(v.allow_local_tx).lower()}   # true : station partagée, l'émission au micro du poste n'est coupée que par tot_abs_s",
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
    for client in cfg.clients:
        lines += ["[[clients]]", f"id = {_s(client.id)}"]
        if client.password_hash:
            lines.append(f"password_hash = {_s(client.password_hash)}")
        if client.token:
            lines.append(f"token = {_s(client.token)}   # ancien secret en clair : à remplacer")
        lines.append("")
    for b in cfg.bands:
        lines += ["[[bands]]", f"name = {_s(b.name)}", f"low_mhz = {b.low_mhz}",
                  f"high_mhz = {b.high_mhz}", ""]
    return "\n".join(lines).rstrip() + "\n"
