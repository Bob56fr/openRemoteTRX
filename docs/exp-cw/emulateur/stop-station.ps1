# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Arrête la station factice CW et elle seule (processus de station_cw.py et ceux qui écoutent sur 18443, 14532, 47910)
$ids = @()
$ids += (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'station_cw|cw-essai' }).ProcessId
$ids += (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 18443, 14532, 47910 }).OwningProcess
foreach ($id in ($ids | Where-Object { $_ } | Sort-Object -Unique)) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -notmatch 'emulator|qemu|adb') { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; "arrêté $id $($p.ProcessName)" }
}
