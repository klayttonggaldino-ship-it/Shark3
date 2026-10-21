# Baixa o Deno (runtime JavaScript exigido pelo yt-dlp para o YouTube) para a pasta bin\
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'bin'
if (Test-Path (Join-Path $bin 'deno.exe')) { Write-Host 'Deno já está em bin\deno.exe'; exit 0 }
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$zip = Join-Path $bin 'deno.zip'
$url = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'
Write-Host "Baixando Deno de $url ..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $bin -Force
Remove-Item $zip
& (Join-Path $bin 'deno.exe') --version
