#requires -Version 5.1
<#
.SYNOPSIS
  Cria o atalho "Mangaba" na Área de Trabalho (Windows): dois cliques sobem o
  Docker Desktop se preciso, rodam `docker compose up -d` e abrem o navegador
  em http://127.0.0.1:8765.

.DESCRIPTION
  Equivalente Windows de packaging/instalar_atalho_desktop.sh. Não empacota um
  app nativo (isso é o Tauri/build_windows.ps1, que precisa rodar EM um Windows
  de verdade) — este atalho é a via rápida: o mesmo container que roda no
  macOS e no Linux, chamado por um .lnk com o ícone da manga.

.USO
  powershell -ExecutionPolicy Bypass -File packaging\instalar_atalho_desktop.ps1
#>
$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath("Desktop")
$Icone = Join-Path $Repo "docs\assets\mangaba-icon.ico"
$ScriptAlvo = Join-Path $Repo "packaging\abrir_mangaba.ps1"

# -- 1. o script que o atalho executa ------------------------------------------------
@"
`$ErrorActionPreference = "Stop"
`$repo = "$Repo"

# Sobe o Docker Desktop se ele ainda não estiver rodando, e espera o daemon acordar.
if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
    Start-Process "`$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
}
`$pronto = `$false
for (`$i = 0; `$i -lt 45; `$i++) {
    docker info *> `$null
    if (`$LASTEXITCODE -eq 0) { `$pronto = `$true; break }
    Start-Sleep -Seconds 2
}
if (-not `$pronto) {
    [System.Windows.Forms.MessageBox]::Show(
        "O Docker não respondeu em 90 segundos. Abra o Docker Desktop e tente de novo.",
        "Mangaba") | Out-Null
    exit 1
}

Push-Location `$repo
docker compose up -d
Pop-Location

for (`$i = 0; `$i -lt 60; `$i++) {
    try {
        `$r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/v1/health" -TimeoutSec 2 -UseBasicParsing
        if (`$r.StatusCode -eq 200) { break }
    } catch { Start-Sleep -Seconds 2 }
}
Start-Process "http://127.0.0.1:8765"
"@ | Set-Content -Path $ScriptAlvo -Encoding UTF8

# -- 2. o atalho .lnk com o ícone da manga -------------------------------------------
Add-Type -AssemblyName System.Windows.Forms
$Wsh = New-Object -ComObject WScript.Shell
$Atalho = $Wsh.CreateShortcut((Join-Path $Desktop "Mangaba.lnk"))
$Atalho.TargetPath = "powershell.exe"
$Atalho.Arguments = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptAlvo`""
$Atalho.IconLocation = $Icone
$Atalho.WorkingDirectory = $Repo
$Atalho.Description = "Abrir o Mangaba"
$Atalho.Save()

Write-Host "Pronto: $Desktop\Mangaba.lnk"
Write-Host "Dois cliques nele sobem o Docker e abrem o Mangaba em http://127.0.0.1:8765"
