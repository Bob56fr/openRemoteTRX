@echo off
rem SPDX-License-Identifier: AGPL-3.0-or-later
rem Copyright (C) 2026 RF-DIY.COM
rem Console de la station openRemoteTRX : double-clic = connexion SSH avec un tunnel, console web ouverte dans le
rem navigateur de ce PC. Fabrique par la page de pilotage de la station ; ne contient AUCUN secret (adresse, compte,
rem ports). Ferme la fenetre pour tout arreter.
set "TRX_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Get-Content -LiteralPath $env:TRX_SELF -Raw -Encoding UTF8; Invoke-Expression ($t.Substring($t.IndexOf('#' + 'PS-BEGIN#')))"
if errorlevel 1 pause
exit /b
#PS-BEGIN#
# Partie PowerShell (Windows PowerShell 5.1), lue et lancée par les lignes ci-dessus.
$Station = '@@HOST@@'
$User = '@@USER@@'
$SshPort = @@SSH_PORT@@
$WebPort = @@WEB_PORT@@

$Safe = $Station -replace '[^A-Za-z0-9.-]', '_'
$Name = "Console de la station ($Safe)"
$Home2 = Join-Path $env:LOCALAPPDATA 'OpenRemoteTRX'
$Installed = Join-Path $Home2 "console-$Safe.cmd"
$Key = Join-Path (Join-Path $env:USERPROFILE '.ssh') "trx-console-$Safe"
$NoKey = Join-Path $Home2 "sans-cle-$Safe"
try { $Host.UI.RawUI.WindowTitle = $Name } catch { }

function Say([string] $Text, [string] $Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }

Say "Console de la station $Station" Cyan
Say "Garde cette fenêtre ouverte pendant que tu utilises la console ; la fermer arrête tout."
Say ""

if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)) {
    Say "Le client SSH de Windows est absent." Red
    Say "Paramètres > Système > Fonctionnalités facultatives > Ajouter « Client OpenSSH », puis relance ce raccourci."
    exit 1
}

# Premier lancement (fichier téléchargé) : rangé dans le dossier de l'utilisateur, raccourci posé sur le Bureau.
if ($env:TRX_SELF -ne $Installed) {
    try {
        New-Item -ItemType Directory -Force -Path $Home2 | Out-Null
        Copy-Item -LiteralPath $env:TRX_SELF -Destination $Installed -Force
        Unblock-File -LiteralPath $Installed
        $Desktop = [Environment]::GetFolderPath('Desktop')
        $Shell = New-Object -ComObject WScript.Shell
        $Link = $Shell.CreateShortcut((Join-Path $Desktop "$Name.lnk"))
        $Link.TargetPath = $Installed
        $Link.WorkingDirectory = $Home2
        $Link.IconLocation = "$env:SystemRoot\System32\shell32.dll,15"
        $Link.Description = "Console de la station openRemoteTRX ($Station)"
        $Link.Save()
        Say "Raccourci « $Name » posé sur le Bureau : la prochaine fois, double-clic dessus." Green
        Say "(Le fichier téléchargé peut être supprimé.)"
        Say ""
    } catch {
        Say "Raccourci du Bureau impossible à créer ($($_.Exception.Message)) : la console s'ouvre quand même." Yellow
    }
}

# Clé SSH proposée une fois : plus de mot de passe SSH ensuite (la clé reste sur ce PC, sa partie publique va sur la
# station). Le mot de passe sudo des menus d'administration reste demandé dans la console.
if (-not (Test-Path -LiteralPath $Key) -and -not (Test-Path -LiteralPath $NoKey) -and -not $env:TRX_CONSOLE_REMOTE) {
    Say "Ce PC peut garder une clé SSH pour ne plus te demander le mot de passe SSH de la station."
    $Answer = Read-Host "Créer la clé maintenant ? (O/N)"
    if ($Answer -match '^\s*[oOyYjJsS]') {
        New-Item -ItemType Directory -Force -Path (Split-Path $Key) | Out-Null
        & ssh-keygen.exe -q -t ed25519 -N '""' -C 'trx-console' -f $Key
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath "$Key.pub")) {
            $Pub = (Get-Content -LiteralPath "$Key.pub" -Raw).Trim()
            Say "Mot de passe SSH du compte $User demandé une dernière fois :" Cyan
            $Remote = "umask 077; mkdir -p ~/.ssh && printf '%s\n' '$Pub' >> ~/.ssh/authorized_keys"
            & ssh.exe -p $SshPort -o StrictHostKeyChecking=accept-new "$User@$Station" $Remote
            if ($LASTEXITCODE -eq 0) {
                Say "Clé installée sur la station." Green
            } else {
                Say "Clé non installée (mot de passe refusé ou station injoignable) : elle sera reproposée." Yellow
                Remove-Item -LiteralPath $Key, "$Key.pub" -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        New-Item -ItemType Directory -Force -Path $Home2 | Out-Null
        New-Item -ItemType File -Force -Path $NoKey | Out-Null
    }
    Say ""
}

$Command = "trx-console --web --raccourci --port $WebPort"
if ($env:TRX_CONSOLE_REMOTE) { $Command = $env:TRX_CONSOLE_REMOTE }       # essais seulement
$SshArgs = @('-tt', '-p', "$SshPort", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ExitOnForwardFailure=yes',
             '-L', "$($WebPort):127.0.0.1:$($WebPort)")
if (Test-Path -LiteralPath $Key) { $SshArgs += @('-i', $Key) }
$SshArgs += @("$User@$Station", $Command)

Say "Connexion à $Station (compte $User)…" Cyan
$Opened = $false
& ssh.exe @SshArgs | ForEach-Object {
    $Line = "$_"
    if (-not $Opened -and $Line -match 'TRX-CONSOLE-URL (http://127\.0\.0\.1:\d+/\?t=[A-Za-z0-9_-]+)') {
        $Opened = $true
        Say "Console ouverte dans le navigateur. Ferme cette fenêtre quand tu as fini." Green
        if (-not $env:TRX_CONSOLE_NO_BROWSER) { Start-Process $Matches[1] }
    } elseif ($Line -notmatch 'TRX-CONSOLE-URL|^Console web de la station|usage unique|Depuis un autre PC|Ctrl\+C pour') {
        Write-Host $Line
    }
}
$Code = $LASTEXITCODE
if ($Opened) { exit 0 }
Say ""
Say "La console n'a pas pu s'ouvrir (code $Code)." Red
Say "  - la station est-elle allumée et joignable à l'adresse $Station ?"
Say "  - une autre fenêtre « Console de la station » est-elle déjà ouverte ? Ferme-la."
Say "  - mot de passe SSH refusé ? C'est celui du compte $User de la station."
exit 1
