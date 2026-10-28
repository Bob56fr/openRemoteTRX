# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
# Installation de TRX distant sous Windows 10 / 11 (lancée par installer.cmd).
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
$AppName = "TRX distant"
$TaskName = "TRX distant"
$Base = if ($Destination) { $Destination } else { Join-Path $env:LOCALAPPDATA "Programs\TRX distant" }
$DataDir = Join-Path $env:ProgramData "trx-remote"
$Config = Join-Path $DataDir "station.toml"
$LogDir = Join-Path $DataDir "logs"
$MenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TRX distant"
$FirewallGroup = "TRX distant"
$MinPython = [version]"3.11"
$HamlibPage = "https://github.com/Hamlib/Hamlib/releases"
$KeepVersions = 2

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
Write-Host "TRX distant $Version : installation pour Windows" -ForegroundColor White
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
    New-Item -ItemType Directory -Force -Path $MenuDir | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $MenuDir "$Name.lnk"))
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.Description = $Description
    $link.WorkingDirectory = $WorkDir
    $link.Save()
}

# ------------------------------------------------------------------ désinstallation

if ($Desinstaller) {
    Step "Désinstallation de TRX distant"
    Stop-Station
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetFirewallRule -Group $FirewallGroup -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (Test-Path -LiteralPath $MenuDir) { Remove-Item -LiteralPath $MenuDir -Recurse -Force }
    if (Test-Path -LiteralPath $Base) { Remove-Item -LiteralPath $Base -Recurse -Force }
    Ok "logiciel, tâche de démarrage, règles du pare-feu et raccourcis retirés"
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
Ok "aucune station en marche pendant l'installation"

# ------------------------------------------------------------------ 3. logiciel et modules Python

Step "3/7 Logiciel et modules Python (quelques minutes, Internet nécessaire)"
$Release = Join-Path $Base "versions\$Version"
if (Test-Path -LiteralPath $Release) { Remove-Item -LiteralPath $Release -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Release | Out-Null
Copy-Item -Path (Join-Path $Here "app") -Destination $Release -Recurse
& $Python -m venv (Join-Path $Release "venv")
if ($LASTEXITCODE -ne 0) { Fail "création de l'environnement Python impossible." }
$VenvPy = Venv-Python $Release
& $VenvPy -m pip install --disable-pip-version-check --upgrade pip | Out-Host
& $VenvPy -m pip install --disable-pip-version-check "$(Join-Path $Release 'app')[station]" | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "installation des modules Python impossible (Internet ? pare-feu d'entreprise ?)." }
& $VenvPy -c "import trxstation, aiohttp, aiortc, sounddevice, cryptography, serial; print('modules OK')"
if ($LASTEXITCODE -ne 0) { Fail "modules Python incomplets." }
Ok "TRX distant $Version installé dans $Release"

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
    New-NetFirewallRule -DisplayName "TRX distant ($([IO.Path]::GetFileName($program)))" -Group $FirewallGroup -Direction Inbound `
        -Action Allow -Program $program -Profile Private | Out-Null
}
New-NetFirewallRule -DisplayName "TRX distant (page web, port $port)" -Group $FirewallGroup -Direction Inbound -Action Allow `
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
    -Description "Station TRX distant : superviseur, rigctld et passerelle (sans fenêtre). Journaux : $LogDir" -Force | Out-Null
Ok "la station démarre à l'ouverture de session de $me (tâche planifiée « $TaskName », sans fenêtre)"

$py = Venv-Python $Current
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (Test-Path -LiteralPath $MenuDir) { Remove-Item -LiteralPath $MenuDir -Recurse -Force }
New-Shortcut "1 - Configuration de la station" $py "-m trxstation.setup_wizard --output `"$Config`"" "Assistant : poste, ports, cartes son, réseau, comptes" $DataDir
New-Shortcut "2 - Diagnostic" $ps "-NoExit -Command `"& '$py' -m trxstation.console --diagnostic --config '$Config'`"" "Contrôle complet, lecture seule" $DataDir
New-Shortcut "3 - Démarrer la station" $ps "-Command `"Start-ScheduledTask -TaskName '$TaskName'; Write-Host 'Station démarrée.'; Start-Sleep 3`"" "Démarre la station en arrière-plan" $DataDir
New-Shortcut "4 - Arrêter la station" $ps "-NoExit -Command `"& '$py' -m trxstation.supervisor.main --config '$Config' --stop`"" "Arrête la station (le poste revient en réception)" $DataDir
New-Shortcut "5 - Tableau de bord" $py "-m trxstation.monitor.main --config `"$Config`"" "État en direct ; touche STOP TX" $DataDir
New-Shortcut "6 - Essai du poste" $py "-m trxstation.devtools.hwtest --config `"$Config`"" "Essai guidé (arrêter la station avant)" $DataDir
New-Shortcut "7 - Journaux de la station" "explorer.exe" "`"$LogDir`"" "Dossier des journaux" $DataDir
New-Shortcut "8 - Mode d'emploi Windows" (Join-Path $Current "notice-windows.html") "" "Notice d'installation et d'utilisation" $DataDir
New-Shortcut "9 - Désinstaller" $ps "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Release 'installer.ps1')`" -Desinstaller" "Retire TRX distant" $env:TEMP
Ok "raccourcis dans le menu Démarrer > TRX distant"
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
    Warn "station non configurée : menu Démarrer > TRX distant > « 1 - Configuration de la station », puis « 3 - Démarrer »."
}

Write-Host ""
Write-Host "Installation terminée (TRX distant $Version)." -ForegroundColor Green
Say "Page web : https://<adresse-de-ce-PC>:$port depuis le téléphone (même réseau), ou https://localhost:$port ici."
Say "Mode d'emploi : menu Démarrer > TRX distant > « 8 - Mode d'emploi Windows »."
try { Stop-Transcript | Out-Null } catch { }
Pause-End
