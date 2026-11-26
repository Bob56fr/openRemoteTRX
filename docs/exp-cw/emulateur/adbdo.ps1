# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
param([string]$Steps = "", [string]$Shot = "s")
# Suite d'actions adb séparées par « | » : tap x y, text ..., key N, wait s, swipe x1 y1 x2 y2 [ms], sh ... ; puis capture
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
foreach ($step in $Steps.Split("|")) {
    $p = $step.Trim().Split(" ", 2)
    if (-not $p[0]) { continue }
    switch ($p[0]) {
        "tap"  { $c = $p[1].Split(" "); & $adb shell input tap $c[0] $c[1] }
        "text" { & $adb shell input text $p[1] }
        "key"  { & $adb shell input keyevent $p[1] }
        "wait" { Start-Sleep -Milliseconds ([int]([double]$p[1] * 1000)) }
        "swipe" { $c = $p[1].Split(" "); $d = if ($c.Length -gt 4) { $c[4] } else { 300 }; & $adb shell input swipe $c[0] $c[1] $c[2] $c[3] $d }
        "sh"   { & $adb shell $p[1] }
    }
    Start-Sleep -Milliseconds 400
}
& $adb shell screencap -p /sdcard/s.png
& $adb pull /sdcard/s.png "C:\dev\cw-essai\$Shot.png" | Out-Null
