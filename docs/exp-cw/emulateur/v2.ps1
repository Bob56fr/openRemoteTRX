# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# V2 (« hang ») de bout en bout : installation de l'APK, connexion, onglet CW, émission autorisée, armement,
# un point, pause (PTT relâché, CW armée), un second point 2 s après (reprise), suivi de l'état et son copié
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt }
function Find($label) {
    & $adb shell uiautomator dump /sdcard/ui.xml | Out-Null
    $xml = (& $adb shell cat /sdcard/ui.xml) -join ""
    $m = [regex]::Match($xml, "text=`"$([regex]::Escape($label))`"[^>]*?bounds=`"\[(\d+),(\d+)\]\[(\d+),(\d+)\]`"")
    if (-not $m.Success) { return $null }
    return @([int](([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2), [int](([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2), [int]$m.Groups[1].Value)
}
function Shot($n) { & $adb shell screencap -p /sdcard/s.png; & $adb pull /sdcard/s.png "C:\dev\cw-essai\$n.png" | Out-Null }
& $adb install -r "C:\dev\openRemoteTRX-cw-and\android\app\build\outputs\apk\debug\app-debug.apk" | Out-Null
& $adb shell am start -n com.rfdiy.openremotetrx/.app.MainActivity | Out-Null
Start-Sleep 4
$c = Find "Connect"; if ($c) { & $adb shell input tap $c[0] $c[1]; Start-Sleep 8 }
& $adb shell input tap 626 2270; Start-Sleep 2
$sw = Find "Transmit allowed"; $arm = Find "ARM CW"
& $adb shell input tap ($sw[2] - 90) $sw[1]; Start-Sleep 1
& $adb shell input tap $arm[0] $arm[1]
for ($i = 0; $i -lt 30 -and (Ptt).state -ne "TX"; $i++) { Start-Sleep -Milliseconds 100 }
"armé : $((Ptt).state)"
$p2 = Find "2 paddles"
$y = if ($p2) { $p2[1] + 400 } else { 1900 }
& $adb shell "input swipe 280 $y 280 $y 80"
$t = Get-Date
$log = @()
for ($i = 0; $i -lt 40; $i++) { $p = Ptt; $log += "$([int]((Get-Date) - $t).TotalMilliseconds):$($p.state)/$($p.last_cut_reason)"; Start-Sleep -Milliseconds 50 }
"après le 1er point : $($log -join ' ')" | Out-String -Width 400
Shot "v1"
Start-Sleep -Milliseconds 300
& $adb shell "input swipe 280 $y 280 $y 80"
$t = Get-Date
$log = @()
for ($i = 0; $i -lt 50; $i++) { $p = Ptt; $log += "$([int]((Get-Date) - $t).TotalMilliseconds):$($p.state)"; Start-Sleep -Milliseconds 50 }
"après le 2e point : $($log -join ' ')" | Out-String -Width 400
Shot "v2"
$c = Find "✕ Close"; if (-not $c) { $c = @(906, 158) }
& $adb shell input tap 906 158; Start-Sleep 1
"fin : $((Ptt).state) « $((Ptt).last_cut_reason) »"
Get-Content C:\dev\cw-essai\station.log | Select-String -Pattern "gateway.cw|ORT-5031" | Select-Object -Last 8
Get-ChildItem C:\dev\cw-essai\emis-*.wav | Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { Copy-Item $_.FullName C:\dev\cw-essai\copie.wav -Force }
