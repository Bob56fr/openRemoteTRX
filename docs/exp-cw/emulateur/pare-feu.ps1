# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
param([ValidateSet("ouvrir", "fermer")][string]$Action = "ouvrir")
# Règle TEMPORAIRE pour qu'un vrai téléphone joigne la station factice CW : Python du venv d'essai, réseau PRIVÉ
# seulement (page et API en TCP 18443, son WebRTC en UDP sur des ports choisis par aiortc). « fermer » la retire.
$name = "openRemoteTRX CW - essai"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Action -eq "ouvrir") {
    $py = & "C:\dev\openRemoteTRX-tests\.venv\Scripts\python.exe" -c "import sys; print(sys._base_executable)"
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Profile Private -Program $py | Out-Null
    "règle ouverte pour $py (réseau privé)"
} else {
    "règle retirée"
}
