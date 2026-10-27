"""Module Cluster DX, lot 2 : configuration, secrets.toml, éditeur (questions de flux, test obligatoire),
processus du module, lancement par le superviseur, diagnostic, rapport sans secret."""
from __future__ import annotations

import asyncio
import json
import os
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from trxstation import config as cfgmod
from trxstation import diagnostics as d
from trxstation import secretstore
from trxstation.cluster import service as svc
from trxstation.cluster import setup as editor_mod
from trxstation.cluster.feed import CONNECTED, Feed, Source
from trxstation.cluster.tester import NO_SPOT, OK, SourceReport, check_source
from trxstation.devtools.fake_cluster import FakeCluster
from trxstation.report import make_report
from trxstation.setup_wizard import dummy_config

from test_console import console, write_config
from test_diagnostics import FakeSystem, healthy, station

ROOT = Path(__file__).resolve().parents[1]
PW = "Mot-De-Passe-Secret-42"


def cluster_cfg(**changes) -> cfgmod.Config:
    cfg = dummy_config()
    cfg.modules.run = ["cluster"]
    c = cfg.cluster
    c.enabled, c.call = True, "F4XXX"
    c.source = [cfgmod.ClusterSource("on0dxk", "telnet", "on0dxk.dyndns.org", 8000, secret="on0dxk"),
                cfgmod.ClusterSource("cb", "web", url="https://clusterdx.org/spots.php")]
    for key, value in changes.items():
        setattr(c, key, value)
    return cfg

# ------------------------------------------------------------------ configuration


def test_cluster_config_round_trip_and_no_password_in_station_toml():
    cfg = cluster_cfg(modes=["SSB", "FREEDV"], continents=["EU"], blacklist=["SPAM*"])
    text = cfgmod.render_toml(cfg)
    assert "[[cluster.source]]" in text and PW not in text
    back = cfgmod.from_dict(tomllib.loads(text))
    assert back.cluster == cfg.cluster and back.modules.run == ["cluster"]


def test_old_configuration_without_cluster_still_loads():
    cfg = cfgmod.from_dict(tomllib.loads(cfgmod.render_toml(dummy_config()).split("[cluster]")[0]))
    assert cfg.cluster.enabled is False and cfg.cluster.source == []


@pytest.mark.parametrize("change,needle", [
    (dict(call=""), "VOTRE indicatif"),
    (dict(modes=["FT8"]), "modes"),
    (dict(bands=["13m"]), "bands"),
    (dict(continents=["XX"]), "continents"),
    (dict(ttl_min=0), "ttl_min"),
    (dict(blacklist=["bad call"]), "blacklist"),
])
def test_cluster_validation_errors(change, needle):
    problems = cfgmod.validate(cluster_cfg(**change))
    assert any(needle in p for p in problems), problems


def test_cluster_source_validation():
    bad = cluster_cfg(source=[cfgmod.ClusterSource("a", "telnet", "h.example", 0),
                              cfgmod.ClusterSource("a", "web", url="http://clusterdx.org/"),
                              cfgmod.ClusterSource("b c", "pigeon"),
                              cfgmod.ClusterSource("d", "rbn", "h", 7000, secret="pas un nom!")])
    text = "\n".join(cfgmod.validate(bad))
    for needle in ("port de 1 à 65535", "nom en double", "url https", "type telnet", "lettres, chiffres", "secret = NOM"):
        assert needle in text, needle


def test_enabled_cluster_must_be_launched_and_have_a_source():
    cfg = cluster_cfg()
    cfg.modules.run = []
    assert any("[modules] run" in p for p in cfgmod.validate(cfg))
    cfg = cluster_cfg(source=[])
    assert any("aucune source" in p for p in cfgmod.validate(cfg))
    web_only = cluster_cfg(call="", source=[cfgmod.ClusterSource("cb", "web", url="https://clusterdx.org/spots.php")])
    assert cfgmod.validate(web_only) == []                  # la page des cibistes ne demande pas d'indicatif


def test_disabled_cluster_needs_nothing():
    cfg = dummy_config()
    cfg.cluster.source = [cfgmod.ClusterSource("x", "telnet", "h.example", 7300)]
    assert cfgmod.validate(cfg) == []

# ------------------------------------------------------------------ secrets.toml


def test_secrets_round_trip_and_rights(tmp_path):
    path = tmp_path / "secrets.toml"
    secretstore.save(path, {"on0dxk": PW, "autre": 'guillemet " et \\ antislash'})
    assert secretstore.load(path) == {"on0dxk": PW, "autre": 'guillemet " et \\ antislash'}
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        os.chmod(path, 0o644)
        assert "0600 attendu" in secretstore.permission_problem(path)
        secretstore.fix_permissions(path)
        assert secretstore.permission_problem(path) is None
    assert secretstore.load(tmp_path / "absent.toml") == {}


def test_secrets_refuse_control_characters_and_never_echo_values(tmp_path):
    with pytest.raises(secretstore.SecretsError):
        secretstore.save(tmp_path / "s.toml", {"x": "abc\r\nSH/DX"})
    bad = tmp_path / "bad.toml"
    bad.write_text(f'[secrets]\nx = "{PW}\n', encoding="utf-8")
    with pytest.raises(secretstore.SecretsError) as err:
        secretstore.load(bad)
    assert PW not in str(err.value)
    assert secretstore.path_for(tmp_path / "station.toml") == tmp_path / "secrets.toml"

# ------------------------------------------------------------------ test d'une source


def test_check_source_reports():
    async def go():
        fake = FakeCluster(interval=0.05)
        await fake.start()
        try:
            ok = await check_source(Source("x", "telnet", "127.0.0.1", fake.port), "F4XXX")
        finally:
            await fake.close()
        quiet = FakeCluster(spots=("rien",), interval=0.05)
        await quiet.start()
        try:
            none = await check_source(Source("x", "telnet", "127.0.0.1", quiet.port), "F4XXX", timeout=6.5)
        finally:
            await quiet.close()
        refused = FakeCluster(refuse_calls=("F4XXX",))
        await refused.start()
        try:
            bad = await check_source(Source("x", "telnet", "127.0.0.1", refused.port), "F4XXX")
        finally:
            await refused.close()
        return ok, none, bad
    ok, none, bad = asyncio.run(go())
    assert ok.ok and ok.cluster_type == "dxspider" and "K1ABC" in ok.sample
    assert none.code == NO_SPOT and "aucun spot" in none.message
    assert bad.code == "callsign_refused" and "indicatif refusé" in bad.message


def test_check_web_source():
    from test_cluster import CDX_NOW, CDX_PAGE
    rep = asyncio.run(check_source(Source("cb", "web", url="https://clusterdx.org/spots.php"), "",
                                   fetch=lambda url: (CDX_PAGE, CDX_NOW)))
    assert rep.ok and rep.spots == 5
    rep = asyncio.run(check_source(Source("cb", "web", url="https://x.example/"), "",
                                   fetch=lambda url: ("<html>maintenance</html>", CDX_NOW)))
    assert rep.code == "format"

# ------------------------------------------------------------------ éditeur (TRX Console, menu 12)


class Script:
    def __init__(self, answers, secrets=(), checks=()):
        self.answers, self.secrets, self.checks = list(answers), list(secrets), list(checks)
        self.out: list[str] = []
        self.checked: list[tuple[str, str, str | None]] = []
        self.written: list[tuple[cfgmod.Config, dict | None]] = []

    def ask(self, prompt):
        self.out.append(prompt)
        assert self.answers, f"question imprévue : {prompt}"
        return self.answers.pop(0)

    def ask_secret(self, prompt):
        self.out.append(prompt)
        return self.secrets.pop(0)

    def check(self, src, call, password):
        self.checked.append((src.name, call, password))
        code = self.checks.pop(0)
        return SourceReport(code, spots=1 if code == OK else 0)

    def editor(self, cfg, secrets=None):
        return editor_mod.ClusterEditor(cfg, Path("station.toml"), ask=self.ask, say=self.out.append,
                                        ask_secret=self.ask_secret, check=self.check, secrets=secrets,
                                        write=lambda c, s: self.written.append((c, s)))


def test_first_configuration_asks_feeds_and_modes_then_tests_each_source():
    answers = ["o", "n", "o",                     # flux : radioamateurs oui, RBN non, cibistes oui
               "n", "o", "o", "o", "o",           # modes : CW non, SSB AM FM FreeDV oui
               "f4xxx", "1", "",                  # indicatif ; serveur n°1 (on0dxk) ; même indicatif
               "o", "1", "", "1",                 # cluster de secours : n°1 restant (db0sue) ; échec -> réessayer
               "14at123", "1",                    # cibistes : indicatif de cibiste, puis clusterdx
               "o", "w"]                          # activer ; enregistrer
    sc = Script(answers, secrets=[PW, ""], checks=[OK, "unreachable", OK, OK])
    assert sc.editor(dummy_config()).run() == 0
    cfg, secrets = sc.written[0]
    c = cfg.cluster
    assert c.enabled and c.call == "F4XXX" and c.cb_call == "14AT123" and c.modes == ["SSB", "AM", "FM", "FREEDV"]
    assert [(s.name, s.type, s.priority) for s in c.source] == [("on0dxk", "telnet", 1), ("db0sue", "telnet", 2),
                                                               ("clusterdx", "web", 1)]
    assert c.source[0].secret == "on0dxk" and secrets == {"on0dxk": PW}
    assert cfg.modules.run == ["cluster"] and cfgmod.validate(cfg) == []
    assert [x[0] for x in sc.checked] == ["on0dxk", "db0sue", "db0sue", "clusterdx"]    # test avant chaque ajout
    assert sc.checked[0][2] == PW
    assert PW not in "\n".join(sc.out) and PW not in cfgmod.render_toml(cfg)


def test_failed_test_drops_the_source_and_its_password():
    cfg = cluster_cfg()
    answers = ["a", "1", "1", "", "3", "q", "o"]     # ajouter un cluster (db0sue), échec -> abandonner, quitter
    sc = Script(answers, secrets=["autre-secret"], checks=["unreachable"])
    ed = sc.editor(cfg, secrets={"on0dxk": PW})
    assert ed.run() == 1 and not sc.written
    assert [s.name for s in ed.c.source] == ["on0dxk", "cb"] and ed.secrets == {"on0dxk": PW}


def test_saving_a_failed_source_needs_an_explicit_yes():
    sc = Script(["a", "1", "1", "", "2", "o", "w"], secrets=[""], checks=["unreachable"])
    ed = sc.editor(cluster_cfg(), secrets={"on0dxk": PW})
    assert ed.run() == 0
    assert any(s.name == "db0sue" for s in sc.written[0][0].cluster.source)


def test_delete_source_removes_its_password_and_disable_module_unregisters_it():
    sc = Script(["s", "1", "o", "e", "w"])
    ed = sc.editor(cluster_cfg(), secrets={"on0dxk": PW})
    assert ed.run() == 0
    cfg, secrets = sc.written[0]
    assert [s.name for s in cfg.cluster.source] == ["cb"] and secrets == {}
    assert not cfg.cluster.enabled and "cluster" not in cfg.modules.run


def test_rbn_without_cw_offers_to_add_cw():
    cfg = cluster_cfg(source=[cfgmod.ClusterSource("rbn-cw", "rbn", "telnet.reversebeacon.net", 7000)])
    sc = Script(["n", "o", "n", "n", "o", "n", "n", "n", "o", "q", "o"])
    ed = sc.editor(cfg)
    ed.flux()
    assert ed.c.modes == ["CW", "SSB"] and any("RBN ne fournit que de la CW" in x for x in sc.out)


def test_invalid_state_is_not_saved():
    cfg = cluster_cfg()
    sc = Script(["i", "", "w", "q", "o"])
    ed = sc.editor(cfg)
    ed.c.call = ""
    ed.c.source[0].call = ""
    assert ed.run() == 1 and not sc.written
    assert any("VOTRE indicatif" in x for x in sc.out)


def test_editor_real_write(tmp_path):
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    ed = editor_mod.ClusterEditor(cfgmod.load(path), path, ask=lambda _: "w", say=lambda _: None,
                                  secrets={"on0dxk": PW})
    ed.cfg = cluster_cfg()
    ed.c = ed.cfg.cluster
    ed.secrets_changed = True
    assert ed.save()
    assert cfgmod.load(path).cluster.source[0].secret == "on0dxk"
    assert secretstore.load(tmp_path / "secrets.toml") == {"on0dxk": PW}
    assert PW not in path.read_text(encoding="utf-8")


def test_console_menu_12_runs_the_editor_as_admin_then_offers_restart(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["o"], running=True)
    con.cluster()
    cmd, admin = fake.calls[0]
    assert "trxstation.cluster.setup" in cmd and admin
    assert fake.calls[-1][0][:2] == ["systemctl", "restart"]

# ------------------------------------------------------------------ processus du module


def test_build_sources_and_missing_password():
    sources, problems = svc.build_sources(cluster_cfg().cluster, {})
    assert [s.name for s in sources] == ["on0dxk", "cb"] and sources[0].password is None
    assert any("absent de secrets.toml" in p for p in problems) and all(PW not in p for p in problems)
    sources, problems = svc.build_sources(cluster_cfg().cluster, {"on0dxk": PW})
    assert sources[0].password == PW and problems == []


def test_health_colors():
    f = Feed([Source("a", "telnet", "h", 1), Source("b", "telnet", "h", 2), Source("r", "rbn", "h", 3)], "F4XXX",
             lambda s, l: None)
    assert svc.health(f, None) == svc.RED
    f.states["b"].state = CONNECTED                          # un cluster sur deux suffit au groupe
    assert svc.health(f, None) == svc.ORANGE                 # RBN absent
    f.states["r"].state = CONNECTED
    engine = SimpleNamespace(last_spot_age=lambda: 30.0)
    assert svc.health(f, engine) == svc.GREEN
    assert svc.health(f, SimpleNamespace(last_spot_age=lambda: None)) == svc.ORANGE
    assert svc.health(None, None) == svc.OFF


def test_service_end_to_end_writes_status_and_tells_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "STATUS_EVERY_S", 0.1)
    messages = []

    class Bus:
        async def client_message(self, **m):
            messages.append(m)

        async def run_forever(self):
            await asyncio.Event().wait()

    async def go():
        fake = FakeCluster(interval=0.05)
        await fake.start()
        cfg = cluster_cfg(source=[cfgmod.ClusterSource("local", "telnet", "127.0.0.1", fake.port)],
                          cty_update=False)
        cfg.supervisor.state_dir = str(tmp_path)
        service = svc.ClusterService(cfg, tmp_path / "station.toml", bus_client=Bus())
        task = asyncio.ensure_future(service.run())
        try:
            for _ in range(100):
                await asyncio.sleep(0.1)
                if svc.status_path(cfg).exists():
                    data = json.loads(svc.status_path(cfg).read_text(encoding="utf-8"))
                    if data["health"] == svc.GREEN:
                        return data
            raise AssertionError("module jamais connecté")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await fake.close()
    data = asyncio.run(go())
    assert data["sources"]["local"]["state"] == "connected" and data["counters"]["received"] > 0
    assert data["cty"]["problem"] and "absent" in data["cty"]["problem"]
    assert any(m.get("health") == svc.GREEN and m["module"] == "cluster" for m in messages)


def test_disabled_service_publishes_off(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "STATUS_EVERY_S", 0.05)
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path)

    async def go():
        task = asyncio.ensure_future(svc.ClusterService(cfg, tmp_path / "station.toml").run())
        await asyncio.sleep(0.3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(go())
    assert json.loads(svc.status_path(cfg).read_text(encoding="utf-8"))["health"] == svc.OFF


def test_cluster_manifest_has_no_right_on_the_rig():
    from trxstation.modules.manifest import load_manifest
    m = load_manifest(ROOT / "trxstation" / "modules" / "builtin" / "cluster" / "manifest.toml")
    assert m.entry == "trxstation.cluster.service"
    assert not m.rights.commands and m.rights.events == frozenset({"freq_mode"}) and m.rights.client_messages


def test_supervisor_gives_the_config_path_to_modules(tmp_path):
    from trxstation.modules.supervisor_glue import build_launcher
    cfg = cluster_cfg()
    cfg.supervisor.state_dir = str(tmp_path)
    launcher = build_launcher(cfg, config_path=Path("station.toml"))
    env = launcher.env_for(launcher.modules["cluster"].manifest)
    assert env["TRX_CONFIG_PATH"] == str(Path("station.toml").resolve())
    assert PW not in "".join(env.values())

# ------------------------------------------------------------------ diagnostic, rapport, import, paquet


def _status(tmp_path, *, time=995.0, **sources):
    return json.dumps({"time": time, "health": "green",
                       "sources": {k: {"state": v, "message": "serveur injoignable"} for k, v in sources.items()},
                       "counters": {"last_spot_age_s": 12.0, "per_minute": 4, "cache": 30, "malformed": 0},
                       "cty": {"problem": None}})


def _cluster_station(tmp_path):
    sysm, _ = healthy(tmp_path)
    cfg = cluster_cfg()
    cfg.rig.model, cfg.rig.port = 3094, "/dev/serial/by-id/usb-IC-7300"
    cfg.supervisor.state_dir = str(tmp_path / "state")
    cfg.supervisor.status_path = str(tmp_path / "status.json")
    path = tmp_path / "station.toml"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return sysm, path, cfg


def test_diagnostic_cluster_checks(tmp_path):
    sysm, path, cfg = _cluster_station(tmp_path)
    spath = str(tmp_path / "secrets.toml")
    status = str(Path(cfg.supervisor.state_dir) / "cluster" / "status.json")
    checks = d.check_cluster(sysm, cfg, path)
    assert any(c.name == "secrets.toml" and c.status == d.FAIL and "absent" in c.message for c in checks)
    assert any(c.name == "Module" and c.status == d.WARN for c in checks)
    sysm.stats[spath] = SimpleNamespace(st_mode=0o100644)
    sysm.files[Path(status).as_posix()] = _status(tmp_path, on0dxk="connected", cb="reconnecting")
    checks = d.check_cluster(sysm, cfg, path)
    by = {c.name: c for c in checks}
    assert by["secrets.toml"].status == d.FAIL and "chmod 600" in by["secrets.toml"].fix
    assert by["Source on0dxk"].status == d.OK and by["Source cb"].status == d.WARN
    assert by["Dernier spot"].status == d.OK
    sysm.stats[spath] = SimpleNamespace(st_mode=0o100600)
    sysm.files[Path(status).as_posix()] = _status(tmp_path, time=900.0, on0dxk="connected")
    by = {c.name: c for c in d.check_cluster(sysm, cfg, path)}
    assert by["secrets.toml"].status == d.OK and "arrêté ou bloqué" in by["Module"].message


def test_report_contains_cluster_state_but_never_the_secrets(tmp_path):
    sysm, path, cfg = _cluster_station(tmp_path)
    secretstore.save(tmp_path / "secrets.toml", {"on0dxk": PW})
    sysm.files[str(path)] = path.read_text(encoding="utf-8")
    sysm.files[(tmp_path / "secrets.toml").as_posix()] = (tmp_path / "secrets.toml").read_text(encoding="utf-8")
    status = Path(cfg.supervisor.state_dir) / "cluster" / "status.json"
    sysm.files[status.as_posix()] = sysm.files[str(status)] = _status(tmp_path, on0dxk="connected")
    target = make_report(tmp_path, sysm=sysm, config_path=path)
    with zipfile.ZipFile(target) as archive:
        everything = b"".join(archive.read(n) for n in archive.namelist()).decode("utf-8")
        assert "cluster-etat.json" in archive.namelist() and "secrets.toml" not in archive.namelist()
    assert PW not in everything and '"on0dxk"' in everything


def test_import_from_windows_says_passwords_must_be_typed_again():
    from trxstation.migrate import import_config
    _, notes = import_config(cluster_cfg(), desktop=True)
    assert any("NON repris" in n and "on0dxk" in n for n in notes)


def test_package_and_git_never_carry_secrets(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bdz", ROOT / "scripts" / "build_debian_zip.py")
    bdz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bdz)
    (tmp_path / "trxstation").mkdir()
    (tmp_path / "docs").mkdir()
    for name in ("secrets.toml", "station.toml", "ok.py"):
        (tmp_path / "trxstation" / name).write_text("x", encoding="utf-8")
    names = [n for n, _ in bdz._app_files(tmp_path)]
    assert "app/trxstation/ok.py" in names and not any(n.endswith(("secrets.toml", "/station.toml")) for n in names)
    assert "secrets.toml" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    install = (ROOT / "debian" / "install.sh").read_text(encoding="utf-8")
    assert "secrets.toml" not in install                     # une mise à jour n'y touche jamais
