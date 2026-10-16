# Taskbar Widgets

Dua widget kecil untuk taskbar Windows 11, ditulis dengan Python + Pillow + tkinter.

| Folder | Isinya |
| --- | --- |
| `AIUsageBar/` | Sisa jatah **Claude Code** (persen besar + hitung mundur reset), di ujung kiri taskbar |
| `NetSpeedBar/` | Kecepatan upload/download (oranye), tepat di kanan widget Claude |

Keduanya bisa diklik untuk panel detail, diseret untuk pindah posisi, dan klik kanan untuk
menu (satuan, transparansi, autostart, keluar). Posisi dan setelan disimpan di
`%LOCALAPPDATA%\AIUsageBar\` dan `%LOCALAPPDATA%\NetSpeedBar\`, bukan di repo ini.

## Pasang ulang di laptop baru

1. Pasang **Python 3.13** dari python.org (centang *Add python.exe to PATH*).
2. Unduh repo ini (tombol **Code → Download ZIP**, atau `git clone`), lalu taruh dua foldernya
   di folder profil, jadi `%USERPROFILE%\AIUsageBar` dan `%USERPROFILE%\NetSpeedBar`.
   Lokasi lain juga bisa; skripnya mencari filenya sendiri dari lokasinya.
3. Jalankan di PowerShell dari folder repo:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   Skrip itu memasang `psutil` dan `Pillow`, mendaftarkan kedua widget supaya jalan setiap
   Windows menyala, menambahkan hook status line Claude Code ke `~\.claude\settings.json`
   (hanya kalau belum ada; salinan lama disimpan sebagai `settings.json.bak-taskbarwidgets`),
   lalu langsung menyalakan kedua widget.

Angka Claude baru muncul setelah Claude Code sudah login dan dipakai sekali, karena sumber
datanya adalah hook status line (`AIUsageBar/statusline.py`) yang ditulis setiap kali
Claude Code menggambar status line-nya.

## Yang sengaja tidak ada di sini

Tidak ada kunci API, token, atau file login. Widget hanya membaca file yang sudah ditulis
Claude Code di komputer sendiri (`~/.claude/usage-state.json`, `~/.claude.json`) dan tidak
memanggil API mana pun.
