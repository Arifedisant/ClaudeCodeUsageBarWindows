# Pasang ulang AIUsageBar + NetSpeedBar di komputer baru.
# Pakai: powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Opsional: -AppRoot <folder> kalau dua folder widget ditaruh di tempat lain.
param(
    [string]$AppRoot = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw 'python.exe tidak ditemukan. Pasang Python 3.13 dulu (centang Add to PATH).' }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }

$usage = Join-Path $AppRoot 'AIUsageBar'
$net = Join-Path $AppRoot 'NetSpeedBar'
foreach ($d in $usage, $net) {
    if (-not (Test-Path $d)) { throw "Folder tidak ada: $d" }
}

Write-Host '1/4 Memasang psutil dan Pillow...'
& $py -m pip install --user --upgrade -r (Join-Path $PSScriptRoot 'requirements.txt')

Write-Host '2/4 Mendaftarkan autostart...'
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty $run 'AIUsageBar' ('"{0}" "{1}"' -f $pyw, (Join-Path $usage 'aiusagebar.pyw'))
Set-ItemProperty $run 'NetSpeedBar' ('"{0}" "{1}"' -f $pyw, (Join-Path $net 'netspeedbar.pyw'))

Write-Host '3/4 Hook status line Claude Code...'
$hook = Join-Path $usage 'statusline.py'
$merge = @'
import json, os, pathlib, shutil, sys
py, hook = sys.argv[1], sys.argv[2]
path = pathlib.Path(os.path.expanduser("~/.claude/settings.json"))
data = {}
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
if "statusLine" in data:
    print("   statusLine sudah ada, tidak diubah:", data["statusLine"].get("command"))
    sys.exit(0)
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    shutil.copy2(path, path.with_name("settings.json.bak-taskbarwidgets"))
data["statusLine"] = {"type": "command", "command": '"%s" "%s"' % (py, hook), "padding": 0}
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("   statusLine ditambahkan.")
'@
$tmp = Join-Path $env:TEMP 'taskbarwidgets-merge.py'
Set-Content -Path $tmp -Value $merge -Encoding utf8
& $py -I $tmp $py $hook
Remove-Item $tmp

Write-Host '4/4 Menyalakan widget...'
Start-Process $pyw ('"{0}"' -f (Join-Path $usage 'aiusagebar.pyw'))
Start-Sleep -Seconds 2
Start-Process $pyw ('"{0}"' -f (Join-Path $net 'netspeedbar.pyw'))

Write-Host 'Selesai. Buka Claude Code sekali supaya angka Claude terisi.'
