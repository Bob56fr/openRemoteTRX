# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Essai de manipulation : (ré)arme si besoin, points tenus 1 s, traits tenus 1 s ; état de la station et capture
param([string]$Shot = "k1", [switch]$Arm)
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt | Select-Object state, owner, last_cut_reason | ConvertTo-Json -Compress }
"avant : $(Ptt)"
if ($Arm) { & $adb shell input tap 775 1315; Start-Sleep -Milliseconds 1500; "armé : $(Ptt)" }
$t = Get-Date
& $adb shell "input swipe 280 1800 280 1800 1000; sleep 0.5; input swipe 800 1800 800 1800 1000"
"manipulation envoyée en $([int]((Get-Date) - $t).TotalMilliseconds) ms"
Start-Sleep -Milliseconds 800
"après : $(Ptt)"
& $adb shell screencap -p /sdcard/s.png
& $adb pull /sdcard/s.png "C:\dev\cw-essai\$Shot.png" | Out-Null
Start-Sleep -Seconds 9
"9 s plus tard : $(Ptt)"
Get-Content C:\dev\cw-essai\station.log | Select-String -Pattern "cw|ORT-50|ORT-40" | Select-Object -Last 8
