# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Vecteurs du protocole de diffusion (tests/protocol/diffusion_vectors.json).

Clé, heures et corps FIXES : relus par les tests de la station et par ceux du serveur (dépôt privé du VPS, même
fichier) : mêmes octets signés, même signature. Refabriquer : python -m trxstation.diffusion.vectors
"""
from __future__ import annotations

import json
from pathlib import Path

from . import protocol as p

OUTPUT = Path(__file__).resolve().parents[2] / "tests" / "protocol" / "diffusion_vectors.json"
KEY = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
STATION = "bob56fr"

SIGNED = [
    ("meta privée, pseudo seul", "meta",
     lambda: p.meta_body(STATION, 1800000000000, "prive", {"pseudo": "BOB-56-FR"})),
    ("meta publique, tous les champs", "meta",
     lambda: p.meta_body(STATION, 1800000001000, "public", {
         "pseudo": "BOB-56-FR", "indicatif": "F4XYZ", "frequence_hz": 7074000, "mode": "USB", "bande": "40m",
         "tx": False, "s_metre": "S9+20", "message": "Écoute du soir"})),
    ("meta publique, silence hors bandes", "meta",
     lambda: p.meta_body(STATION, 1800000003000, "public", {"pseudo": "BOB-56-FR"}, "hors_bandes")),
    ("meta publique, S-mètre animé, filtre et voyants", "meta",
     lambda: p.meta_body(STATION, 1800000004000, "public", {
         "pseudo": "BOB-56-FR", "frequence_hz": 7074000, "mode": "USB", "s_metre": "S7", "filtre": "2.4k",
         "voyants": [["P.AMP 1", True], ["ATT", False], ["ΔTX", False], ["NB", True]],
         "s": [[0, -12.0, None], [200, -10.5, True], [400, -14, False]]})),
    ("nouveau mot de passe des auditeurs", "auditeur",
     lambda: p.listener_body(STATION, 1800000002000, "auditeur", "Abcdef123456")),
]

META_REFUSED = [
    ("champ inconnu", {"adresse_ip": "192.0.2.1"}),
    ("voyant sans booléen", {"voyants": [["NB", "oui"]]}),
    ("voyant trop long", {"voyants": [["x" * 13, True]]}),
    ("point du S-mètre trop vieux", {"s": [[10001, 0, None]]}),
    ("point du S-mètre hors échelle", {"s": [[0, 101, None]]}),
    ("point du S-mètre incomplet", {"s": [[0, 1]]}),
    ("texte trop long", {"pseudo": "x" * 33}),
    ("fréquence négative", {"frequence_hz": -1}),
    ("booléen pris pour un entier", {"frequence_hz": True}),
    ("texte pris pour un booléen", {"tx": "oui"}),
    ("caractère de contrôle", {"message": "a\u0007b"}),
]


def build() -> dict:
    key = bytes.fromhex(KEY)
    out: dict = {
        "protocole": "diffusion openRemoteTRX v1 (docs/protocole-diffusion.md) : X-Orx-Signature = HMAC-SHA256(clé, "
                     "MÉTHODE + \"\\n\" + chemin + \"\\n\" + corps) en hexadécimal minuscule ; corps = octets UTF-8 "
                     "exacts envoyés (JSON compact, sans échappement des accents). Fabriqué par "
                     "python -m trxstation.diffusion.vectors : ne pas modifier à la main.",
        "signatures": [],
    }
    for name, action, body in SIGNED:
        path = p.api_path(STATION, action)
        data = body()
        out["signatures"].append({"nom": name, "cle": KEY, "methode": "POST", "chemin": path,
                                  "corps": data.decode("utf-8"), "signature": p.sign(key, "POST", path, data)})
    out["source"] = {
        "hote": "diffusion.example.org", "port": 8443, "station": STATION, "acces": "prive", "codec": "opus",
        "mot_de_passe": "MotSource42", "nom": "BOB-56-FR",
        "requete": p.source_request("diffusion.example.org", 8443, STATION, "prive", "MotSource42", "opus",
                                    "BOB-56-FR").decode("utf-8"),
    }
    out["meta_refusees"] = [{"nom": n, "meta": m} for n, m in META_REFUSED]
    out["silences"] = list(p.SILENCE_REASONS)
    out["reconnexion_s"] = [p.backoff(i) for i in range(1, 9)]
    return out


def main() -> None:
    OUTPUT.write_bytes((json.dumps(build(), ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{OUTPUT} écrit")


if __name__ == "__main__":
    main()
