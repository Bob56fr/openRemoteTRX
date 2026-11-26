# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Deuxième série : STOP chronométré sans la recherche du bouton, Close examiné, réseau coupé après 4 s d'armement
$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
function Ptt { (Get-Content C:\dev\cw-essai\station\etat\status.json -Raw | ConvertFrom-Json).ptt }
function Find($label) {
    & $adb shell uiautomator dump /sdcard/ui.xml | Out-Null
    $xml = (& $adb shell cat /sdcard/ui.xml) -join ""
    $m = [regex]::Match($xml, "text=`"$([regex]::Escape($label))`"[^>]*?bounds=`"\[(\d+),(\d+)\]\[(\d+),(\d+)\]`"")
    if (-not $m.Success) { return $null }
    return @([int](([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2), [int](([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2))
}
function Shot($n) { & $adb shell screencap -p /sdcard/s.png; & $adb pull /sdcard/s.png "C:\dev\cw-essai\$n.png" | Out-Null }
function WaitRx($t0) {
    for ($i = 0; $i -lt 100; $i++) {
        $p = Ptt
        if ($p.state -eq "RX") { return "RX en $([int]((Get-Date) - $t0).TotalMilliseconds) ms, cause « $($p.last_cut_reason) »" }
        Start-Sleep -Milliseconds 50
    }
    "TOUJOURS EN TX après 5 s"
}
function Arm {
    if (-not (Find "ARM CW")) {
        $c = Find "Connect"; if ($c) { & $adb shell input tap $c[0] $c[1]; Start-Sleep 8 }
        & $adb shell input tap 626 2270; Start-Sleep 2
    }
    Start-Sleep 4
    $p = Find "ARM CW"; if (-not $p) { "  ARM CW introuvable"; Shot "x-arm"; return $false }
    & $adb shell input tap $p[0] $p[1]
    for ($i = 0; $i -lt 30; $i++) { if ((Ptt).state -eq "TX") { return $true }; Start-Sleep -Milliseconds 100 }
    "  pas armé"; return $false
}
"1. STOP (bouton repéré avant)"
if (Arm) { $s = Find "STOP"; Start-Sleep 1; $t = Get-Date; & $adb shell input tap $s[0] $s[1]; WaitRx $t }
"2. Close"
if (Arm) { $c = Find "Close"; "  Close en $c"; Start-Sleep 1; $t = Get-Date; & $adb shell input tap $c[0] $c[1]; WaitRx $t; Start-Sleep 1; Shot "x-close" }
"3. Réseau coupé après 4 s d'armement sans manipuler"
if (Arm) {
    Start-Sleep 4
    "  avant la coupure : $((Ptt).state)"
    $t = Get-Date; & $adb shell "svc wifi disable; svc data disable"; "  coupure envoyée en $([int]((Get-Date) - $t).TotalMilliseconds) ms"; WaitRx $t
    & $adb shell "svc wifi enable; svc data enable"
}
Get-Content C:\dev\cw-essai\station.log | Select-String -Pattern "gateway.cw|ORT-5031|ORT-4020|closed|ferm" | Select-Object -Last 10
