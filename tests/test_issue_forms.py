# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Tickets par poste (étape 409) : liste déroulante des formulaires, étiquette poste:N, lecture par la station."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

from trxstation.changes import issues as iss

ROOT = Path(__file__).resolve().parents[1]


def forms_module():
    spec = importlib.util.spec_from_file_location("build_issue_forms", ROOT / "scripts" / "build_issue_forms.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_form_has_the_rig_dropdown_with_the_hamlib_number_and_is_up_to_date():
    mod = forms_module()
    forms = mod.forms()
    assert len(forms) == 8 and {mod.form_lang(f) for f in forms} == {"fr", "en", "de", "es"}
    for path in forms:
        assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == mod.render(path), \
            "relancer python scripts/build_issue_forms.py"
        field = next(b for b in yaml.safe_load(path.read_text(encoding="utf-8"))["body"] if b.get("id") == "trx")
        options = field["attributes"]["options"]
        assert field["type"] == "dropdown" and "Icom IC-7300MK2 (Hamlib 3094)" in options
        assert "Yaesu FTDX10 (Hamlib 1042)" in options and len(options) == len(set(options))
        assert field["validations"]["required"] is ("-bug-" in path.name)


def test_the_label_workflow_never_puts_the_issue_body_in_the_script():
    text = (ROOT / ".github" / "workflows" / "issue-labels.yml").read_text(encoding="utf-8")
    run = yaml.safe_load(text)["jobs"]["label"]["steps"][0]["run"]
    assert "${{" not in run and '"$BODY"' in run and r"\(Hamlib [0-9]{4}\)" in run


def api_item(number, state="open", **over):
    item = {"number": number, "title": f"Ticket {number}", "state": state, "created_at": "2026-11-20T10:00:00Z",
            "closed_at": None, "html_url": f"{iss.ISSUE_PREFIX}{number}"}
    item.update(over)
    return item


def test_api_answer_is_cleaned_and_foreign_links_and_pull_requests_are_dropped(tmp_path):
    raw = json.dumps([api_item(1), api_item(2, state="closed", closed_at="2026-11-21T00:00:00Z"),
                      api_item(3, pull_request={}), api_item(4, html_url="https://exemple.invalid/4"),
                      api_item(5, title="\x1b[31mrouge\x1b[0m piégé")]).encode()
    found = iss.parse_api(raw)
    assert [i.number for i in found] == [1, 2, 5] and found[1].closed == "2026-11-21" and not found[1].open
    assert "\x1b" not in found[2].title and "rouge" in found[2].title
    assert iss.api_url(3094).endswith("labels=poste:3094&state=all&per_page=50")
    iss.cache_path(tmp_path).parent.mkdir(parents=True)
    iss.cache_path(tmp_path).write_bytes(iss.to_cache(3094, found, now=1.0))
    assert iss.load_cached(tmp_path, 3094) == (found, 1.0) and iss.load_cached(tmp_path, 1042) is None


def test_update_check_saves_the_issues_of_the_rig_and_menu_shows_them(tmp_path):
    from test_console import console

    from trxstation import config as cfgmod
    from trxstation.setup_wizard import dummy_config
    from trxstation.update.check import fetch_issues
    state = tmp_path / "state"
    urls = []
    def fetch(url):
        urls.append(url)
        return json.dumps([api_item(7, title="FIL bloqué")]).encode()
    assert fetch_issues(state, 3094, fetch) and urls == [iss.api_url(3094)]
    assert not fetch_issues(state, 0, fetch)
    cfg = dummy_config()
    cfg.rig.model, cfg.supervisor.state_dir = 3094, str(state)
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, _, out = console(tmp_path, answers=["2", "n"])
    con.changes()
    text = "\n".join(out)
    assert "1 ouvert(s), 0 fermé(s)" in text and "#7" in text and "FIL bloqué" in text
    assert "label%3Aposte%3A3094" in text
