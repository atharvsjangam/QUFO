$ErrorActionPreference = 'Stop'
$qufoRoot = Split-Path -Parent $PSScriptRoot
$qufoPython = Join-Path $qufoRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $qufoPython)) { throw 'Run SETUP.cmd first.' }
$qufoDesktop = [Environment]::GetFolderPath('Desktop')
$qufoShell = New-Object -ComObject WScript.Shell
$qufoShortcut = $qufoShell.CreateShortcut((Join-Path $qufoDesktop 'QUFO.lnk'))
$qufoShortcut.TargetPath = $qufoPython
$qufoShortcut.Arguments = '"' + (Join-Path $qufoRoot 'scripts\launch.py') + '"'
$qufoShortcut.WorkingDirectory = $qufoRoot
$qufoShortcut.IconLocation = (Join-Path $qufoRoot 'static\qufo.ico')
$qufoShortcut.Description = 'QUFO - Quick Info knowledge workspace'
$qufoShortcut.WindowStyle = 7
$qufoShortcut.Save()
Write-Output ('QUFO shortcut created on ' + $qufoDesktop)
