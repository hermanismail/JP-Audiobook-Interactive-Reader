# Creates "SHAMA Server.lnk" on the Desktop, pointing at the launcher's own
# venv pythonw.exe (pythonw = no console window behind the GUI).
#
# Run once:   powershell -ExecutionPolicy Bypass -File create-shortcut.ps1
# Then right-click the Desktop shortcut -> "Pin to taskbar".
#
# Windows pins the shortcut itself, so the taskbar button keeps working even
# if the Desktop copy is later deleted.

$ErrorActionPreference = "Stop"

$launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw     = Join-Path $launcherDir ".venv\Scripts\pythonw.exe"
$script      = Join-Path $launcherDir "launcher.py"
$icon        = Join-Path $launcherDir "icon.ico"
$shortcut    = Join-Path ([Environment]::GetFolderPath("Desktop")) "SHAMA Server.lnk"

if (-not (Test-Path $pythonw)) {
    Write-Host "Launcher venv not found at $pythonw" -ForegroundColor Red
    Write-Host "Create it first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($shortcut)
$lnk.TargetPath       = $pythonw
$lnk.Arguments        = '"' + $script + '"'
$lnk.WorkingDirectory = $launcherDir
$lnk.Description      = "Start the SHAMA audiobook server and Cloudflare tunnel"
if (Test-Path $icon) { $lnk.IconLocation = $icon }
$lnk.Save()

Write-Host "Created: $shortcut" -ForegroundColor Green
Write-Host "Right-click it and choose 'Pin to taskbar'." -ForegroundColor Green
