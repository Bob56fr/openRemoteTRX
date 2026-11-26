# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
param([Parameter(Mandatory)][string]$MotDePasse, [string]$Dossier = "C:\dev\cw-essai")
# Lance la station factice CW hors de la session SSH, journal dans $Dossier\station.log
$py = "C:\dev\openRemoteTRX-tests\.venv\Scripts\python.exe"
$wav = "$Dossier\emis-$(Get-Date -Format HHmmss).wav"
$cmd = "cmd /c `"`"$py`" `"$Dossier\station_cw.py`" --dossier `"$Dossier\station`" --mot-de-passe $MotDePasse --enregistrer `"$wav`" > `"$Dossier\station.log`" 2>&1`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $Dossier }
"pid $($r.ProcessId) code $($r.ReturnValue) wav $wav"
Start-Sleep -Seconds 12
Get-Content "$Dossier\station.log" -Tail 15
netstat -an | Select-String ":18443 |:14532 "
