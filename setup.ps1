# Pasang AI Usage Bar di komputer baru.
# Pakai (dari folder ini): powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Stop'

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw 'python.exe tidak ditemukan. Pasang Python 3.13 dulu (centang Add to PATH).' }
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
$app = Join-Path $PSScriptRoot 'aiusagebar.pyw'
$hook = Join-Path $PSScriptRoot 'statusline.py'

Write-Host '1/4 Memasang Pillow...'
& $py -m pip install --user --upgrade -r (Join-Path $PSScriptRoot 'requirements.txt')

Write-Host '2/4 Mendaftarkan autostart...'
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' 'AIUsageBar' ('"{0}" "{1}"' -f $pyw, $app)

Write-Host '3/4 Hook status line Claude Code...'
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
    shutil.copy2(path, path.with_name("settings.json.bak-aiusagebar"))
data["statusLine"] = {"type": "command", "command": '"%s" "%s"' % (py, hook), "padding": 0}
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("   statusLine ditambahkan.")
'@
$tmp = Join-Path $env:TEMP 'aiusagebar-merge.py'
Set-Content -Path $tmp -Value $merge -Encoding utf8
& $py -I $tmp $py $hook
Remove-Item $tmp

Write-Host '4/4 Menyalakan widget...'
Start-Process $pyw ('"{0}"' -f $app)
Write-Host 'Selesai. Buka Claude Code sekali supaya angkanya terisi.'
