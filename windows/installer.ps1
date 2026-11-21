# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Installation d'openRemoteTRX sous Windows 10 / 11 (lancée par installer.cmd).
#   installer.cmd                 installe ou met à jour (la configuration est conservée)
#   installer.cmd -Desinstaller   retire le logiciel (la configuration est gardée, sauf réponse contraire)
#   installer.cmd -Essai -Destination DOSSIER   essai sans rien toucher au système (ni tâche, ni pare-feu, ni raccourci)
# Rien n'est envoyé au poste pendant l'installation. La station démarre toujours en réception.
[CmdletBinding()]
param(
    [switch]$Desinstaller,
    [switch]$Essai,
    [string]$Destination = "",
    [switch]$SansQuestion
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = (Get-Content -LiteralPath (Join-Path $Here "VERSION") -Raw).Trim()
$AppName = "openRemoteTRX"
$TaskName = "TRX distant"
$Base = if ($Destination) { $Destination } else { Join-Path $env:LOCALAPPDATA "Programs\TRX distant" }
$DataDir = Join-Path $env:ProgramData "trx-remote"
$Config = Join-Path $DataDir "station.toml"
$LogDir = Join-Path $DataDir "logs"
# UN SEUL raccourci (étape 222, décision du 2026-11-16) : « openRemoteTRX » ouvre openRemoteTRX Console, qui regroupe tout.
$Shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\openRemoteTRX.lnk"
# Raccourci des versions 0.258.0 et avant (nom affiché « TRX distant », étape 345) : retiré à l'installation
$OldShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TRX distant.lnk"
# Dossier de 10 raccourcis des versions jusqu'à 0.168.0 : retiré à l'installation et à la désinstallation.
$MenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TRX distant"
# Inscription dans Paramètres > Applications (désinstallation comme tout logiciel Windows), pour ce compte seulement.
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TRX distant"
$GuideUrl = "https://bob56fr.github.io/openRemoteTRX/guide/"
# Indicateur près de l'horloge (trxstation/tray, lecture seule) : raccourci du dossier Démarrage de la session.
$TrayStartup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\TRX distant - indicateur.lnk"
$FirewallGroup = "TRX distant"
$MinPython = [version]"3.11"
$HamlibPage = "https://github.com/Hamlib/Hamlib/releases"
$KeepVersions = 2
# Commandes lançables depuis n'importe quel terminal (comme COMMANDS d'install.sh sous Debian) : toutes celles de
# [project.scripts] SAUF trx-gateway, trx-rigctld et trx-supervisor (une seconde instance à côté de la tâche planifiée
# n'a rien à faire en ligne de commande). Le test test_windows_package l'impose.
$Commands = @("trx-console", "trx-setup", "trx-monitor", "trx-hwtest", "trx-qualif", "trx-journal-android", "trx-netreport", "trx-sdr")
$BinDir = Join-Path $Base "bin"

function Say([string]$Text) { Write-Host $Text }
function Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "  [ATTENTION] $Text" -ForegroundColor Yellow }
function Fail([string]$Text) {
    Write-Host ""; Write-Host "  [ÉCHEC] $Text" -ForegroundColor Red
    Write-Host "  Rien n'a été modifié sur le poste. Compte-rendu : $script:Transcript"
    Pause-End; exit 1
}
function Pause-End { if (-not $SansQuestion) { Read-Host "`nEntrée pour fermer" | Out-Null } }
function Ask-Yes([string]$Question, [bool]$Default) {
    if ($SansQuestion) { return $Default }
    $hint = if ($Default) { "O/n" } else { "o/N" }
    $answer = (Read-Host "$Question ($hint)").Trim().ToUpperInvariant()
    if (-not $answer) { return $Default }
    return @("O", "OUI", "Y", "YES") -contains $answer
}
function Is-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ------------------------------------------------------------------ droits administrateur (pare-feu, dossier protégé)

if (-not $Essai -and -not (Is-Admin)) {
    Say "L'installation demande les droits administrateur (pare-feu, protection de la configuration)."
    $elevArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$($MyInvocation.MyCommand.Path)`"")
    if ($Desinstaller) { $elevArgs += "-Desinstaller" }
    if ($SansQuestion) { $elevArgs += "-SansQuestion" }
    try { Start-Process powershell.exe -Verb RunAs -WorkingDirectory $env:TEMP -ArgumentList $elevArgs | Out-Null }
    catch { Write-Host "Droits administrateur refusés : installation annulée." -ForegroundColor Red; Pause-End }
    exit 0
}

Set-Location -LiteralPath $env:TEMP                 # jamais dans un dossier que l'installation remplace ou efface
$script:Transcript = Join-Path $env:TEMP "trx-remote-install.log"
try { Start-Transcript -LiteralPath $script:Transcript -Append | Out-Null } catch { }

Write-Host ""
Write-Host "openRemoteTRX $Version : installation pour Windows" -ForegroundColor White
Write-Host "Dossier du logiciel : $Base"
Write-Host "Configuration       : $Config"

# ------------------------------------------------------------------ outils

function Venv-Python([string]$Root, [string]$Exe = "python.exe") { return Join-Path $Root "venv\Scripts\$Exe" }

function Station-Running {
    $current = Join-Path $Base "current"
    $py = Venv-Python $current
    if (-not (Test-Path -LiteralPath $py)) { return $false }
    & $py -c "from trxstation.procutil import acquire_instance_lock as a; s = a(47321); import sys; sys.exit(0 if s is None else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Stop-Station {
    $current = Join-Path $Base "current"
    $py = Venv-Python $current
    if ((Test-Path -LiteralPath $py) -and (Test-Path -LiteralPath $Config)) {
        & $py -m trxstation.supervisor.main --config $Config --stop
    }
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
}

function Find-Python {
    # Python 3.11 ou plus récent ; jamais l'alias du Microsoft Store (WindowsApps), qui ouvre la boutique.
    $candidates = New-Object System.Collections.Generic.List[string]
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($line in (& $launcher.Source -0p 2>$null)) {
            if ($line -match '(\S+python\.exe)\s*$') { $candidates.Add($Matches[1]) }
        }
    }
    foreach ($dir in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles", "${env:ProgramFiles(x86)}")) {
        if ($dir -and (Test-Path -LiteralPath $dir)) {
            Get-ChildItem -LiteralPath $dir -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
                ForEach-Object { $candidates.Add((Join-Path $_.FullName "python.exe")) }
        }
    }
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates.Add($onPath.Source) }
    $best = $null; $bestVersion = [version]"0.0"
    foreach ($exe in $candidates) {
        if (-not (Test-Path -LiteralPath $exe) -or $exe -match "WindowsApps") { continue }
        $text = (& $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($text -and ([version]$text) -ge $MinPython -and ([version]$text) -gt $bestVersion) { $best = $exe; $bestVersion = [version]$text }
    }
    return $best
}

function Find-Rigctld {
    $onPath = Get-Command rigctld.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    foreach ($pattern in @("$env:ProgramFiles\hamlib*", "${env:ProgramFiles(x86)}\hamlib*", "C:\hamlib*")) {
        $found = Get-ChildItem -Path $pattern -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "bin\rigctld.exe" } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($found) { return $found }
    }
    $custom = [Environment]::GetEnvironmentVariable("TRX_HAMLIB_DIR", "User")
    if ($custom -and (Test-Path -LiteralPath (Join-Path $custom "bin\rigctld.exe"))) { return (Join-Path $custom "bin\rigctld.exe") }
    return $null
}

function New-Shortcut([string]$Name, [string]$Target, [string]$Arguments, [string]$Description, [string]$WorkDir) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path (Split-Path -Parent $Shortcut) "$Name.lnk"))
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.Description = $Description
    $link.WorkingDirectory = $WorkDir
    $link.Save()
}

# PATH de l'UTILISATEUR (jamais celui du système), lu et écrit dans le registre sans développer les %VARIABLES% :
# [Environment]::GetEnvironmentVariable les remplacerait par leur valeur du moment (REG_EXPAND_SZ perdu).
function Get-UserPath {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment")
    if (-not $key) { return "" }
    try { return [string]$key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    finally { $key.Close() }
}
function Set-UserPath([string]$Value) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Environment")
    try {
        if ($Value) { $key.SetValue("Path", $Value, [Microsoft.Win32.RegistryValueKind]::ExpandString) }
        else { $key.DeleteValue("Path", $false) }
    } finally { $key.Close() }
    # Écrire (puis effacer) une variable par .NET diffuse WM_SETTINGCHANGE : les terminaux ouverts ENSUITE voient le PATH.
    [Environment]::SetEnvironmentVariable("TRX_DISTANT_PATH", "1", "User")
    [Environment]::SetEnvironmentVariable("TRX_DISTANT_PATH", $null, "User")
}
function Same-Dir([string]$A, [string]$B) {
    return [string]::Equals($A.Trim().TrimEnd('\'), $B.Trim().TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
}
function Without-BinDir([string]$PathValue) {
    return @($PathValue -split ';' | Where-Object { $_.Trim() -and -not (Same-Dir $_ $BinDir) }) -join ';'
}
# Un relais .cmd par commande vers la version ACTIVE (jonction current) : une mise à jour ou un retour arrière ne
# change ni le PATH ni les relais. Chemin relatif au relais (%~dp0) : pur ASCII, un nom de compte accentué ne gêne pas.
function Install-Commands {
    if (Test-Path -LiteralPath $BinDir) { Remove-Item -LiteralPath $BinDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    foreach ($cmd in $Commands) {
        $exe = "%~dp0..\current\venv\Scripts\$cmd.exe"
        $lines = @("@echo off", "rem openRemoteTRX : relais vers la version active (cree par installer.ps1)",
                   "if not exist `"$exe`" (echo openRemoteTRX : version active introuvable, relance installer.cmd 1>&2 & exit /b 9009)",
                   "`"$exe`" %*")
        [IO.File]::WriteAllText((Join-Path $BinDir "$cmd.cmd"), (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    }
    $current = Get-UserPath
    $clean = Without-BinDir $current
    $wanted = if ($clean) { "$clean;$BinDir" } else { $BinDir }
    if ($wanted -ne $current) { Set-UserPath $wanted }
}
# L'indicateur tient ouverts les fichiers de SA version : arrêté avant de remplacer ou d'effacer une version.
function Stop-Tray {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'trxstation\.tray' } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null }
}
function Remove-Commands {
    $current = Get-UserPath
    $clean = Without-BinDir $current
    if ($clean -ne $current) { Set-UserPath $clean }
    if (Test-Path -LiteralPath $BinDir) { Remove-Item -LiteralPath $BinDir -Recurse -Force }
}

# ------------------------------------------------------------------ désinstallation

if ($Desinstaller) {
    Step "Désinstallation d'openRemoteTRX"
    Stop-Station
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetFirewallRule -Group $FirewallGroup -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (Test-Path -LiteralPath $MenuDir) { Remove-Item -LiteralPath $MenuDir -Recurse -Force }
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut -Force }
    if (Test-Path -LiteralPath $OldShortcut) { Remove-Item -LiteralPath $OldShortcut -Force }
    if (Test-Path -LiteralPath $UninstallKey) { Remove-Item -LiteralPath $UninstallKey -Recurse -Force }
    Remove-Commands
    Stop-Tray
    if (Test-Path -LiteralPath $TrayStartup) { Remove-Item -LiteralPath $TrayStartup -Force }
    if (Test-Path -LiteralPath $Base) { Remove-Item -LiteralPath $Base -Recurse -Force }
    Ok "logiciel, tâche de démarrage, règles du pare-feu, raccourci, inscription dans Applications et commandes (PATH) retirés"
    if (Test-Path -LiteralPath $DataDir) {
        if (Ask-Yes "Effacer aussi la configuration (comptes, réglages du poste, profils) dans $DataDir" $false) {
            Remove-Item -LiteralPath $DataDir -Recurse -Force
            Ok "configuration effacée"
        } else { Say "  Configuration gardée : $DataDir (reprise par une prochaine installation)." }
    }
    try { Stop-Transcript | Out-Null } catch { }
    Pause-End; exit 0
}

# ------------------------------------------------------------------ 1. vérifications

Step "1/7 Vérifications"
if (-not [Environment]::Is64BitOperatingSystem) { Fail "Windows 64 bits requis." }
$os = [Environment]::OSVersion.Version
if ($os.Major -lt 10) { Fail "Windows 10 ou 11 requis." }
Ok "Windows $($os.Major).$($os.Minor) build $($os.Build), 64 bits"
# Version Microsoft Store déjà installée (même superviseur, même rigctld, même port) : deux stations se disputeraient
# le poste (cahier du Store § 5). Identité : windows/msix/identity.toml.
$StorePackage = Get-AppxPackage -Name "RF-DIY.COM.openRemoteTRX" -ErrorAction SilentlyContinue
if ($StorePackage) {
    Fail "openRemoteTRX du Microsoft Store est déjà installé sur ce PC (version $($StorePackage.Version)) : le zip ne s'installe pas à côté. Gardez la version du Store, ou désinstallez-la d'abord par Paramètres > Applications (la configuration de $DataDir est gardée)."
}

$Python = Find-Python
if (-not $Python) {
    Warn "Python $MinPython ou plus récent est introuvable."
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget -and (Ask-Yes "Installer Python 3.12 maintenant avec winget (Internet nécessaire)" $true)) {
        & $winget.Source install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $Python = Find-Python
    }
    if (-not $Python) { Fail "Installe Python 3.12 depuis https://www.python.org/downloads/windows/ (case « Add python.exe to PATH »), puis relance installer.cmd." }
}
Ok "Python : $Python"

$Rigctld = Find-Rigctld
if (-not $Rigctld) {
    Warn "Hamlib (rigctld.exe) est introuvable. Il pilote le poste : il est indispensable."
    Say "  Télécharge l'installateur Windows 64 bits (hamlib-w64-X.Y.Z.exe) sur $HamlibPage"
    Say "  et installe-le dans le dossier proposé (C:\Program Files\hamlib-w64-X.Y.Z)."
    if (Ask-Yes "Ouvrir cette page maintenant" $true) { Start-Process $HamlibPage }
    $answer = if ($SansQuestion) { "" } else { (Read-Host "Une fois Hamlib installé, Entrée pour continuer (ou chemin du dossier Hamlib s'il est ailleurs)").Trim('" ') }
    if ($answer) {
        if (Test-Path -LiteralPath (Join-Path $answer "bin\rigctld.exe")) {
            if (-not $Essai) { [Environment]::SetEnvironmentVariable("TRX_HAMLIB_DIR", $answer, "User") }
            $env:TRX_HAMLIB_DIR = $answer
        } else { Fail "Pas de bin\rigctld.exe dans $answer." }
    }
    $Rigctld = Find-Rigctld
    if (-not $Rigctld -and $env:TRX_HAMLIB_DIR) { $Rigctld = Join-Path $env:TRX_HAMLIB_DIR "bin\rigctld.exe" }
    if (-not $Rigctld) { Fail "Hamlib toujours introuvable : installe-le puis relance installer.cmd." }
}
$hamlibVersion = (& $Rigctld --version 2>$null | Select-Object -First 1)
Ok "Hamlib : $hamlibVersion"

$free = (Get-PSDrive -Name ($Base.Substring(0, 1))).Free
if ($free -lt 2GB) { Fail "Moins de 2 Go libres sur le disque $($Base.Substring(0, 1)):." }

# ------------------------------------------------------------------ 2. arrêt de la version en marche

Step "2/7 Station en marche"
$WasRunning = $false
if (-not $Essai -and (Station-Running)) {
    $WasRunning = $true
    Say "  La station tourne : elle est arrêtée pendant l'installation (le poste est remis en réception)."
    Stop-Station
}
if (-not $Essai) { Stop-Tray }
Ok "aucune station en marche pendant l'installation"

# ------------------------------------------------------------------ 3. logiciel et modules Python

Step "3/7 Logiciel et modules Python (quelques minutes, Internet nécessaire)"
$Release = Join-Path $Base "versions\$Version"
if (Test-Path -LiteralPath $Release) { Remove-Item -LiteralPath $Release -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Release | Out-Null
Copy-Item -Path (Join-Path $Here "app") -Destination $Release -Recurse
# Décodeurs FreeDV RADE V1 (freedv-ka9q.exe, radae_rx.exe et leurs DLL) : à côté de venv, la station les y trouve
# (trxstation/freedv/service.py, bundled_dir) ; absents d'un paquet fait sans eux.
$FreedvDir = Join-Path $Here "freedv"
if (Test-Path -LiteralPath $FreedvDir) {
    Copy-Item -Path $FreedvDir -Destination $Release -Recurse
    Ok "décodeurs FreeDV copiés (mode FreeDV de la station en réception)"
}
& $Python -m venv (Join-Path $Release "venv")
if ($LASTEXITCODE -ne 0) { Fail "création de l'environnement Python impossible." }
$VenvPy = Venv-Python $Release
# Modules vérifiés par EMPREINTE (app\requirements.lock, scripts/build_lock.py) : un module différent de celui qui a été
# figé fait échouer l'installation ; puis l'application seule, sans rien télécharger d'autre.
$LockFile = Join-Path $Release "app\requirements.lock"
if (-not (Test-Path -LiteralPath $LockFile)) { Fail "paquet sans empreintes des modules Python (app\requirements.lock) : refusé." }
# Échec : EMPREINTE DIFFÉRENTE (ORT-9311, critique : ne jamais contourner) ou autre cause (ORT-9308) ; pip écrit son
# compte-rendu complet dans $PipLog.
$PipLog = Join-Path $env:TEMP ("trx-remote-pip-" + [guid]::NewGuid().ToString("N") + ".log")
& $VenvPy -m pip install --disable-pip-version-check --log $PipLog --require-hashes -r $LockFile | Out-Host
if ($LASTEXITCODE -ne 0) {
    $HashBad = (Test-Path -LiteralPath $PipLog) -and (Select-String -LiteralPath $PipLog -SimpleMatch "DO NOT MATCH THE HASHES" -Quiet)
    Remove-Item -LiteralPath $PipLog -Force -ErrorAction SilentlyContinue
    if ($HashBad) { Fail "ORT-9311 EMPREINTE DIFFÉRENTE d'un module Python : installation arrêtée (fichier altéré, miroir ou proxy qui modifie les téléchargements). Ne pas contourner. https://bob56fr.github.io/openRemoteTRX/erreurs/ORT-9311/" }
    Fail "ORT-9308 installation des modules Python impossible : Internet, pare-feu d'entreprise ou module introuvable. https://bob56fr.github.io/openRemoteTRX/erreurs/ORT-9308/"
}
Remove-Item -LiteralPath $PipLog -Force -ErrorAction SilentlyContinue
& $VenvPy -m pip install --disable-pip-version-check --no-deps --no-build-isolation (Join-Path $Release 'app') | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "installation d'openRemoteTRX impossible." }
& $VenvPy -c "import trxstation, aiohttp, aiortc, sounddevice, cryptography, serial, pystray, PIL; print('modules OK')"
if ($LASTEXITCODE -ne 0) { Fail "modules Python incomplets." }
Ok "openRemoteTRX $Version installé dans $Release"

if ($Essai) {
    & $VenvPy -m trxstation.setup_wizard --help | Select-Object -First 2 | Out-Host
    Ok "ESSAI terminé : rien n'a été modifié dans le système (ni tâche, ni pare-feu, ni raccourci, ni configuration)."
    try { Stop-Transcript | Out-Null } catch { }
    exit 0
}

# Version active : lien « current » (jonction, sans droits particuliers). Les versions plus anciennes au-delà de
# $KeepVersions sont retirées (la précédente reste pour un retour arrière : relancer son installateur).
$Current = Join-Path $Base "current"
if (Test-Path -LiteralPath $Current) { (Get-Item -LiteralPath $Current).Delete() }
New-Item -ItemType Junction -Path $Current -Target $Release | Out-Null
Get-ChildItem -LiteralPath (Join-Path $Base "versions") -Directory | Sort-Object CreationTime -Descending |
    Select-Object -Skip $KeepVersions | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
Ok "version active : $Version"

# ------------------------------------------------------------------ 4. configuration protégée

Step "4/7 Dossier de la configuration"
New-Item -ItemType Directory -Force -Path $DataDir, $LogDir | Out-Null
# station.toml contient les empreintes des mots de passe : seuls ce compte, les administrateurs et le système y ont accès.
$me = "$env:USERDOMAIN\$env:USERNAME"
& icacls $DataDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "${me}:(OI)(CI)M" /T /C /Q | Out-Null
Ok "$DataDir réservé à $me (et aux administrateurs)"

# ------------------------------------------------------------------ 5. pare-feu (réseau privé seulement)

Step "5/7 Pare-feu Windows"
Get-NetFirewallRule -Group $FirewallGroup -ErrorAction SilentlyContinue | Remove-NetFirewallRule
$port = 8443
if (Test-Path -LiteralPath $Config) {
    $match = Select-String -LiteralPath $Config -Pattern '^\s*gateway_port\s*=\s*(\d+)' | Select-Object -First 1
    if ($match) { $port = [int]$match.Matches[0].Groups[1].Value }
}
# Le Python du venv relance l'interpréteur de base : c'est lui qui écoute. Règles par programme (WebRTC : ports UDP
# variables) et par port (page web), sur les réseaux PRIVÉS uniquement (jamais « Public »).
$basePy = (& $VenvPy -c "import sys; print(sys._base_executable)").Trim()
$programs = @($basePy, (Join-Path (Split-Path -Parent $basePy) "pythonw.exe")) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique
foreach ($program in $programs) {
    New-NetFirewallRule -DisplayName "openRemoteTRX ($([IO.Path]::GetFileName($program)))" -Group $FirewallGroup -Direction Inbound `
        -Action Allow -Program $program -Profile Private | Out-Null
}
New-NetFirewallRule -DisplayName "openRemoteTRX (page web, port $port)" -Group $FirewallGroup -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $port -Profile Private | Out-Null
Ok "entrées autorisées sur les réseaux privés (port $port et audio WebRTC)"
$public = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq "Public" }
if ($public) {
    Warn "le réseau « $($public[0].Name) » est en profil PUBLIC : la page web n'y sera pas joignable."
    Say "  Si c'est ton réseau de la maison : Paramètres > Réseau et Internet > (ta connexion) > Profil réseau : Privé."
}

# ------------------------------------------------------------------ 6. démarrage automatique et raccourcis

Step "6/7 Démarrage automatique et menu Démarrer"
$pythonw = Venv-Python $Current "pythonw.exe"
$action = New-ScheduledTaskAction -Execute $pythonw -WorkingDirectory $DataDir `
    -Argument "-m trxstation.supervisor.main --config `"$Config`" --log-dir `"$LogDir`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Station openRemoteTRX : superviseur, rigctld et passerelle (sans fenêtre). Journaux : $LogDir" -Force | Out-Null
Ok "la station démarre à l'ouverture de session de $me (tâche planifiée « $TaskName », sans fenêtre)"

$py = Venv-Python $Current
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (Test-Path -LiteralPath $MenuDir) { Remove-Item -LiteralPath $MenuDir -Recurse -Force }
if (Test-Path -LiteralPath $OldShortcut) { Remove-Item -LiteralPath $OldShortcut -Force }
# PowerShell -NoExit (leçon de l'étape 201) : la fenêtre reste ouverte après une erreur et se ferme quand on quitte
# openRemoteTRX Console normalement (code 0).
New-Shortcut "openRemoteTRX" $ps "-NoExit -Command `"& '$py' -m trxstation.console --config '$Config'; if (`$LASTEXITCODE -eq 0) { exit }`"" "openRemoteTRX Console : démarrer, configurer, essayer, mettre à jour, dépanner" $DataDir
Ok "raccourci « openRemoteTRX » dans le menu Démarrer (openRemoteTRX Console : tous les menus de la station)"
$uninstall = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Release 'installer.ps1')`" -Desinstaller"
New-Item -Path $UninstallKey -Force | Out-Null
foreach ($pair in @(@("DisplayName", "openRemoteTRX"), @("DisplayVersion", $Version), @("Publisher", "RF-DIY.COM"),
                    @("InstallLocation", $Base), @("UninstallString", $uninstall), @("URLInfoAbout", $GuideUrl),
                    @("HelpLink", $GuideUrl), @("DisplayIcon", $py))) {
    New-ItemProperty -Path $UninstallKey -Name $pair[0] -Value $pair[1] -PropertyType String -Force | Out-Null
}
foreach ($flag in @("NoModify", "NoRepair")) {
    New-ItemProperty -Path $UninstallKey -Name $flag -Value 1 -PropertyType DWord -Force | Out-Null
}
Ok "désinstallation : Paramètres > Applications > openRemoteTRX"
Install-Commands
if (Ask-Yes "Afficher l'indicateur de la station près de l'horloge à chaque ouverture de session" $true) {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($TrayStartup)
    $link.TargetPath = $pythonw
    $link.Arguments = "-m trxstation.tray"
    $link.Description = "openRemoteTRX : indicateur près de l'horloge (lecture seule)"
    $link.WorkingDirectory = $DataDir
    $link.Save()
    # Lancé par l'Explorateur : sous TON compte, sans les droits administrateur de l'installation.
    Start-Process explorer.exe -ArgumentList "`"$TrayStartup`""
    Ok "indicateur près de l'horloge (s'il est caché dans « ^ », glisse-le à côté de l'horloge)"
} elseif (Test-Path -LiteralPath $TrayStartup) {
    Remove-Item -LiteralPath $TrayStartup -Force
    Say "  Indicateur non lancé à l'ouverture de session (openRemoteTRX Console, menu 8.4, pour le lancer ou le remettre)."
}
Ok "commandes $($Commands -join ', ') lançables depuis un NOUVEAU terminal (dossier $BinDir ajouté à ton PATH)"
foreach ($file in @("notice-windows.html", "installer.cmd", "installer.ps1", "VERSION", "LICENSE")) {
    Copy-Item -LiteralPath (Join-Path $Here $file) -Destination $Release -Force
}

# ------------------------------------------------------------------ 7. configuration et démarrage

Step "7/7 Configuration"
if (-not (Test-Path -LiteralPath $Config)) {
    Say "  Pas encore de configuration : l'assistant va te demander le poste, les ports, les cartes son et les comptes."
    Say "  Avant : dans Paramètres > Système > Son, la carte son du poste ne doit être ni la sortie ni l'entrée par défaut."
    if (Ask-Yes "Lancer l'assistant de configuration maintenant" $true) {
        & $py -m trxstation.setup_wizard --output $Config
    }
}
if (Test-Path -LiteralPath $Config) {
    & $py -m trxstation.console --diagnostic --config $Config
    if (Ask-Yes "Démarrer la station maintenant" $true) {
        Start-ScheduledTask -TaskName $TaskName
        Ok "station démarrée (journaux : $LogDir)"
    }
} else {
    Warn "station non configurée : menu Démarrer > openRemoteTRX (Console), menu 2.1, puis menu 1.1 pour démarrer."
}

Write-Host ""
Write-Host "Installation terminée (openRemoteTRX $Version)." -ForegroundColor Green
Say "Page web : https://<adresse-de-ce-PC>:$port depuis le téléphone (même réseau), ou https://localhost:$port ici."
Say "Tout se fait depuis le menu Démarrer > openRemoteTRX (Console ; « h » puis un numéro = aide d'un menu)."
Say "Guide de l'opérateur : $GuideUrl ; notice Windows : $(Join-Path $Current 'notice-windows.html')"
try { Stop-Transcript | Out-Null } catch { }
Pause-End
