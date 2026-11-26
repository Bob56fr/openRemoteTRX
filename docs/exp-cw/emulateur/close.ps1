# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Close pendant la CW armée (positions de l'écran du téléphone 1080 × 2400 après les correctifs)
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt }
& $adb shell input tap 775 1362
for ($i = 0; $i -lt 30 -and (Ptt).state -ne "TX"; $i++) { Start-Sleep -Milliseconds 100 }
"armé : $((Ptt).state)"
Start-Sleep 1
$t = Get-Date
& $adb shell input tap 906 158
for ($i = 0; $i -lt 100 -and (Ptt).state -ne "RX"; $i++) { Start-Sleep -Milliseconds 50 }
"RX en $([int]((Get-Date) - $t).TotalMilliseconds) ms, cause « $((Ptt).last_cut_reason) »"
Start-Sleep 1
& $adb shell screencap -p /sdcard/s.png
& $adb pull /sdcard/s.png "C:\dev\cw-essai\c4.png" | Out-Null
