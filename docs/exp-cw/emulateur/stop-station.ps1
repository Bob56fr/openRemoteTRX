# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Arrête la station factice CW et elle seule : tous les processus de station_cw.py, de sa passerelle et de son faux
# rigctld (le Python d'un venv relance l'interpréteur de base : deux processus par programme, tués avec leurs enfants),
# puis ceux qui écoutent encore sur 18443, 14532, 47910. Jamais une station installée (8443, 4532, 47810).
$ids = @()
$ids += (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'cw-essai\\station|station_cw\.py|fake_rigctld --port 14532' -and $_.CommandLine -notmatch 'Get-CimInstance' }).ProcessId
$ids += (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 18443, 14532, 47910 }).OwningProcess
foreach ($id in ($ids | Where-Object { $_ } | Sort-Object -Unique)) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match '^(python|pythonw|cmd)$') { & taskkill /PID $id /T /F 2>$null | Out-Null; "arrêté $id $($p.ProcessName)" }
}
Start-Sleep -Seconds 1
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 18443, 14532, 47910 } |
    ForEach-Object { "ENCORE en écoute : port $($_.LocalPort), processus $($_.OwningProcess)" }
