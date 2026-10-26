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
    allow_local_tx: bool = False      # True : l'émission locale (micro du poste) n'est pas coupée
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
class Update:
    enabled: bool = True              # cherche une nouvelle version au démarrage puis toutes les 24 h (rien n'est installé sans confirmation)
    allow_prerelease: bool = False    # true : propose aussi les pré-versions publiées sur GitHub


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

    for b in cfg.bands:
        if not 0 < b.low_mhz < b.high_mhz:
            p.append(f"[[bands]] '{b.name}' : bornes invalides")
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


def build(d: dict) -> tuple[Config, list[str]]:
    """Construit une Config SANS la refuser : retourne (config, problèmes). Les clés inconnues sont ignorées et signalées.

    Sert à reprendre une configuration incomplète (import depuis un autre PC, assistant relancé) comme base
    de départ. Une config qui sert à faire tourner la station passe TOUJOURS par `from_dict` / `load`.
    """
    problems: list[str] = []
    top_known = {"schema_version", "config_revision", "rig", "audio", "tools", "network",
                 "safety", "supervisor", "modules", "update", "bands", "clients"}
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
        f"allow_local_tx = {str(v.allow_local_tx).lower()}   # true : ne pas couper l'émission au micro du poste",
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
