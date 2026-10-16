# AI Usage Bar

> **Catatan (10 Okt 2026):** versi sekarang hanya menampilkan Claude Code — satu angka persen
> besar + hitung mundur reset (`READERS = (read_claude,)` di `providers.py`). Pembaca Codex dan
> Antigravity yang dijelaskan di bawah masih ada di kode, hanya tidak ditampilkan.

Strip tipis di ujung kiri taskbar Windows 11 yang menunjukkan berapa banyak
jatah **Claude Code**, **Codex**, dan **Antigravity** yang sudah terpakai —
dan tempat login/logout ketiganya.

```
● CLAUDE CODE      55%   ● CODEX          65%   ● ANTIGRAVITY   12 prompt
▓▓▓▓▓▓▓▓░░░░░░░░         ▓▓▓▓▓▓▓▓▓▓▓░░░░         ▁▁▁█▅▁▂▂▂▂
5 jam · reset 4j 20m     30 hari · reset 24hr    5 jam terakhir · 12 hari ini
```

Warna aksen mengikuti merek masing-masing, lalu berubah **kuning di 70%** dan
**merah di 90%**. Bacaan yang sudah kedaluwarsa tidak dipajang seolah-olah masih
akurat — angkanya meredup dan captionnya berganti jadi umur bacaan (`basi 2j lalu`).

## Cara pakai

| Aksi | Hasil |
| --- | --- |
| Klik kartu | Panel detail: semua window limit, akun, tombol Login/Logout/Muat ulang |
| Klik tombol `Login` di kartu | Membuka terminal login untuk AI yang belum masuk |
| Seret | Pindah posisi, tersimpan otomatis |
| Klik kanan | Menu: Akun, muat ulang, transparansi, kembalikan ke pojok, autostart, keluar |

Panel menutup sendiri sedetik setelah pointer pergi.

## Jalan otomatis

Sudah didaftarkan di `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
dengan nama `AIUsageBar`, jadi tiap Windows menyala bar-nya muncul lagi di
tempat yang sama. Mau matikan? Klik kanan → hilangkan centang
**Jalan saat Windows menyala**.

Saat sign-in, taskbar kadang belum ada ketika skripnya jalan. Karena itu bar
mengukur ulang dockingnya di detik ke-1, 2, 5, 12, 25, lalu tiap 30 detik —
juga yang membuatnya menyesuaikan diri kalau resolusi atau skala layar berubah.

Menjalankan manual:

```powershell
Start-Process "C:\Program Files\Python313\pythonw.exe" `
  '"C:\Users\<you>\AIUsageBar\aiusagebar.pyw"'
```

## Dari mana angkanya

Semuanya dibaca dari file yang **memang sudah ditulis** ketiga CLI itu di
komputer ini. Tidak ada panggilan ke API vendor, tidak ada yang mengintip
credential store atau cookie browser — keberadaan file kredensial hanya dipakai
sebagai penanda "sudah login", isinya tidak pernah dibaca.

**Claude Code** — `~/.claude/usage-state.json`, ditulis oleh `statusline.py`
di folder ini. Claude Code memipa JSON sesinya ke hook itu tiap kali status line
digambar; hook menyalin `rate_limits` ke file tadi lalu mencetak status line
kembali. Titik butanya: hook hanya melihat pemakaian yang lewat Claude Code,
padahal jatah 5 jam dan 7 hari dibagi bersama claude.ai dan aplikasi desktop.
Akun dan paket dari `~/.claude.json`.

Hook-nya terdaftar di `~/.claude/settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "\"C:\\Program Files\\Python313\\python.exe\" \"C:\\Users\\<you>\\AIUsageBar\\statusline.py\"",
  "padding": 0
}
```

Kalau blok itu hilang, kartu Claude berhenti diperbarui dan captionnya berganti
jadi umur bacaan. Hook ini tidak pernah melempar exception — hook yang crash
akan mematikan status line semua sesi Claude Code, jadi payload rusak cuma
menghasilkan baris kosong.

**Codex** — objek `rate_limits` terakhir di file sesi terbaru
(`~/.codex/sessions/…/rollout-*.jsonl`): `used_percent`, `window_minutes`,
`resets_at`, dan `plan_type`. File itu bisa puluhan MB dan satu barisnya bisa
lebih besar dari jendela baca mana pun, jadi yang dilakukan adalah menyisir
teks mentah dari ekor file, bukan memecahnya per baris. Codex baru mengirim
angka limit setelah balasan pertama dalam sebuah sesi.

**Antigravity** — status login dan email dari log CLI-nya sendiri
(`applyAuthResult: email=…`). **Sisa kuotanya tidak ada di disk**: quota manager
Antigravity mengambilnya dari `daily-cloudcode-pa.googleapis.com` dan menyimpannya
di memori proses yang sedang jalan. Jadi kartunya menampilkan yang benar-benar
bisa diketahui — jumlah prompt yang kamu kirim dalam 5 jam terakhir dan hari ini —
bukan persentase karangan.

Karena tidak ada persen untuk digambar, baris grafiknya diisi **sparkline
aktivitas**: sepuluh kolom, masing-masing 30 menit, tinggi mengikuti jumlah
prompt di slot itu. Bentuknya sengaja beda dari gauge dua kartu lain supaya
tidak salah dibaca sebagai persen. Kalau kamu tahu sendiri batasnya, isi lewat
klik kanan → **Batas prompt Antigravity…** dan kartunya berubah jadi gauge
sungguhan.

## Login & logout

Claude dan Codex punya sub-perintah auth sungguhan, jadi tombolnya menjalankan
itu di terminal baru:

| | Login | Logout |
| --- | --- | --- |
| Claude Code | `claude auth login` | `claude auth logout` |
| Codex | `codex login` | `codex logout` |
| Antigravity | `agy` (selesaikan di dalam antarmukanya) | idem |

`agy --help` tidak punya verb auth sama sekali, jadi tombolnya membuka CLI-nya
dan menyerahkan urusan itu ke antarmuka Antigravity sendiri, bukan berpura-pura
ada saklar di sini. Selama 25 detik setelah terminal login terbuka, bar berhenti
merebut z-order supaya tidak menutupi jendela yang sedang kamu ketik.

## Susunan file

| Path | |
| --- | --- |
| `aiusagebar.pyw` | jendela, interaksi, menu, aksi login/logout |
| `providers.py` | pembacaan tiga provider; jalankan langsung untuk melihat JSON mentahnya |
| `render.py` | seluruh gambar (Pillow), strip dan panel |
| `statusline.py` | hook Claude Code; satu-satunya sumber kartu Claude |
| `%LOCALAPPDATA%\AIUsageBar\config.json` | posisi, transparansi, batas Antigravity |

Gambarnya tidak dibuat dari widget Tk. Bentuk digambar di layer 3x lalu
diperkecil, teks digambar setelahnya pada ukuran akhir — itu yang bikin sudut
membulat dan track progres setipis 5px tetap halus di skala DPI berapa pun.
Warna latar jendela (`#010203`) di-punch jadi transparan, sengaja nyaris hitam
supaya rumbai anti-aliasing di sudut lebur ke taskbar gelap alih-alih menyala.

## Kalau ada yang aneh

```powershell
py -3 C:\Users\<you>\AIUsageBar\providers.py   # apa yang sebenarnya terbaca
```

Bar tidak muncul setelah boot: pastikan value `AIUsageBar` masih ada di key
`Run`, lalu jalankan manual dengan `python.exe` (bukan `pythonw.exe`) supaya
error-nya kelihatan.
