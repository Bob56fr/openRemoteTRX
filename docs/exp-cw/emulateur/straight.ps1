# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# 1 palette (clé droite) : appui de 700 ms puis de 250 ms ; copie du WAV pour la mesure
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt }
& $adb shell input tap 626 2270; Start-Sleep 2           # onglet CW
& $adb shell input tap 150 1362; Start-Sleep 1           # 1 palette
& $adb shell screencap -p /sdcard/s.png; & $adb pull /sdcard/s.png "C:\dev\cw-essai\d1.png" | Out-Null
Start-Sleep 3
& $adb shell input tap 775 1362
for ($i = 0; $i -lt 30 -and (Ptt).state -ne "TX"; $i++) { Start-Sleep -Milliseconds 100 }
"armé : $((Ptt).state)"
& $adb shell "input swipe 540 1850 540 1850 700; sleep 0.4; input swipe 540 1850 540 1850 250"
Start-Sleep 3
& $adb shell input tap 906 158
Start-Sleep 1
"fin : $((Ptt).state) « $((Ptt).last_cut_reason) »"
Get-ChildItem C:\dev\cw-essai\emis-*.wav | ForEach-Object { Copy-Item $_.FullName C:\dev\cw-essai\copie.wav -Force }
