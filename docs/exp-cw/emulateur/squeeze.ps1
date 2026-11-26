# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Iambique B, deux palettes pressées ensemble, par la console de l'émulateur (« adb emu event send », sans root) :
# point posé, trait posé juste après, les deux tenus $HoldMs, relâchés ; son de la station copié pour la mesure
param([int]$HoldMs = 600, [switch]$NoSetup)
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt }
function Emu([string[]]$events) { $r = & $adb emu event send @events; if ($r -notmatch "OK") { "console : $r" } }
$X1 = 8495; $X2 = 24272; $Y = 25942                       # palettes point et trait (écran 1080 x 2400 -> 0..32767)
if (-not $NoSetup) {
    & $adb shell input tap 366 1494; Start-Sleep 1          # 2 palettes
    & $adb shell input tap 105 1355; Start-Sleep 1          # émission autorisée
}
& $adb shell input tap 776 1495
for ($i = 0; $i -lt 30 -and (Ptt).state -ne "TX"; $i++) { Start-Sleep -Milliseconds 100 }
"armé : $((Ptt).state)"
$t = Get-Date
Emu @("EV_ABS:ABS_MT_SLOT:0", "EV_ABS:ABS_MT_TRACKING_ID:101", "EV_ABS:ABS_MT_POSITION_X:$X1", "EV_ABS:ABS_MT_POSITION_Y:$Y",
      "EV_ABS:ABS_MT_PRESSURE:200", "EV_KEY:330:1", "EV_SYN:0:0")
Emu @("EV_ABS:ABS_MT_SLOT:1", "EV_ABS:ABS_MT_TRACKING_ID:102", "EV_ABS:ABS_MT_POSITION_X:$X2", "EV_ABS:ABS_MT_POSITION_Y:$Y",
      "EV_ABS:ABS_MT_PRESSURE:200", "EV_SYN:0:0")
$t2 = Get-Date
Start-Sleep -Milliseconds $HoldMs
$t3 = Get-Date
Emu @("EV_ABS:ABS_MT_SLOT:0", "EV_ABS:ABS_MT_TRACKING_ID:-1", "EV_SYN:0:0")
Emu @("EV_ABS:ABS_MT_SLOT:1", "EV_ABS:ABS_MT_TRACKING_ID:-1", "EV_KEY:330:0", "EV_SYN:0:0")
"point posé -> trait posé : $([int]($t2 - $t).TotalMilliseconds) ms ; tenus ensemble ~$([int]($t3 - $t2).TotalMilliseconds) ms"
Start-Sleep 3
& $adb shell screencap -p /sdcard/s.png; & $adb pull /sdcard/s.png "C:\dev\cw-essai\f1.png" | Out-Null
& $adb shell input tap 906 158; Start-Sleep 1
"fin : $((Ptt).state) « $((Ptt).last_cut_reason) »"
Get-ChildItem C:\dev\cw-essai\emis-*.wav | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Copy-Item $_.FullName C:\dev\cw-essai\copie.wav -Force }
