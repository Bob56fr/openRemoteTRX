# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# « Émission autorisée » exigée pour armer la CW : refus sans elle, armement avec, désarmement quand on la retire
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
& $adb install -r "C:\dev\openRemoteTRX-cw-and\android\app\build\outputs\apk\debug\app-debug.apk"
& $adb shell am start -n com.rfdiy.openremotetrx/.app.MainActivity | Out-Null
Start-Sleep 4
$c = Find "Connect"; if ($c) { & $adb shell input tap $c[0] $c[1]; Start-Sleep 8 }
& $adb shell input tap 626 2270; Start-Sleep 2
$arm = Find "ARM CW"; $sw = Find "Transmit allowed"
"ARM CW en $($arm[0]),$($arm[1]) ; Transmit allowed en $($sw[0]),$($sw[1]) (texte à partir de x=$($sw[2]))"
Shot "e1"
"1. ARM CW sans « Émission autorisée »"
& $adb shell input tap $arm[0] $arm[1]; Start-Sleep 2
"  station : $((Ptt).state)"
Shot "e2"
"2. « Émission autorisée » puis ARM CW"
& $adb shell input tap ($sw[2] - 90) $sw[1]; Start-Sleep 1
& $adb shell input tap $arm[0] $arm[1]
for ($i = 0; $i -lt 30 -and (Ptt).state -ne "TX"; $i++) { Start-Sleep -Milliseconds 100 }
"  station : $((Ptt).state)"
Shot "e3"
"3. « Émission autorisée » retirée pendant la CW armée"
$t = Get-Date
& $adb shell input tap ($sw[2] - 90) $sw[1]
for ($i = 0; $i -lt 100 -and (Ptt).state -ne "RX"; $i++) { Start-Sleep -Milliseconds 50 }
"  RX en $([int]((Get-Date) - $t).TotalMilliseconds) ms, cause « $((Ptt).last_cut_reason) »"
Start-Sleep 1; Shot "e4"
