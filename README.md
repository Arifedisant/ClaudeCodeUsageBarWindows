# Claude Code Usage Bar untuk Windows 11

Widget kecil di **taskbar Windows 11** yang menunjukkan berapa persen **jatah pemakaian Claude Code**
(Claude dari Anthropic, **bukan** ChatGPT/GPT) yang sudah terpakai, dan **jam berapa jatah itu reset**.

```
 52%        <- persen jatah 5 jam yang sudah terpakai
10:30 AM    <- jam reset (besok 3:50 AM / Sen 7:50 AM kalau lewat hari)
```

Cocok untuk pengguna Claude Code dengan langganan **Claude Pro / Max**, supaya tidak tiba-tiba kena
limit di tengah kerja. Ditulis dengan Python (Pillow + tkinter), satu folder, tanpa installer.

Saudaranya: [Net Speed Bar untuk Windows](https://github.com/Arifedisant/NetSpeedBarWindows), kecepatan
upload/download internet, biasanya dipasang tepat di sebelah kanannya.

## Fitur

- **Persen besar** jatah 5 jam Claude Code, warnanya berubah **kuning di 70%** dan **merah di 90%**.
- **Jam reset** format 12 jam (AM/PM), seperti jam di taskbar. Tulisan mengecil otomatis supaya tetap rata tengah.
- **Klik** = panel detail: jatah 5 jam dan 7 hari, jam reset + sisa waktunya, akun, tombol Login/Logout/Muat ulang.
- **Seret** = pindah posisi (tersimpan). **Klik kanan** = Akun, muat ulang, transparansi, kembalikan ke pojok,
  jalan saat Windows menyala, keluar.
- Latar mengikuti warna taskbar, jadi tampak transparan tapi tetap bisa diklik dan diseret.
- Angka yang sudah basi (Claude Code lama tidak dipakai) tidak dipajang seolah masih akurat: tulisan meredup jadi `basi`.
- Menyesuaikan diri dengan skala layar (DPI) dan resolusi yang berubah.

## Kebutuhan

- Windows 11 (Windows 10 kemungkinan jalan, tapi tidak diuji)
- [Python 3.13](https://www.python.org/downloads/) (centang *Add python.exe to PATH* saat memasang)
- [Claude Code](https://code.claude.com) yang sudah login dengan akun Claude Pro/Max.
  Pengguna API key tidak punya angka jatah, jadi widget akan menunggu terus.

## Pasang

1. Unduh repo ini: tombol hijau **Code → Download ZIP**, lalu ekstrak (atau `git clone`).
2. Taruh foldernya di tempat tetap, misalnya `%USERPROFILE%\ClaudeCodeUsageBar`.
   Jangan di folder Downloads yang suka dibersihkan, karena autostart menunjuk ke lokasi ini.
3. Buka PowerShell di folder itu dan jalankan:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   Skrip itu:
   - memasang `Pillow` lewat pip,
   - mendaftarkan widget supaya jalan setiap Windows menyala (`HKCU\...\CurrentVersion\Run`, nilai `AIUsageBar`),
   - menambahkan hook status line ke `~\.claude\settings.json`, hanya kalau belum ada
     (salinan lama disimpan sebagai `settings.json.bak-aiusagebar`),
   - langsung menyalakan widgetnya.
4. Pakai Claude Code sekali. Setelah itu angkanya muncul dan diperbarui sendiri.

## Dari mana angkanya

Tidak ada API yang dipanggil dan tidak ada kunci/token yang dibaca. Claude Code mengirim data sesinya
ke perintah **status line** setiap kali status line digambar. `statusline.py` memakai panggilan itu untuk
menyalin bagian `rate_limits` (persen + waktu reset) ke `~\.claude\usage-state.json`, lalu widget membaca
file itu. Nama akun dan paket dibaca dari `~\.claude.json`.

Hook yang dipasang `setup.ps1` di `~\.claude\settings.json` bentuknya seperti ini:

```json
"statusLine": {
  "type": "command",
  "command": "\"C:\\Program Files\\Python313\\python.exe\" \"C:\\Users\\<you>\\ClaudeCodeUsageBar\\statusline.py\"",
  "padding": 0
}
```

Kalau blok itu hilang, angka berhenti diperbarui dan tulisan berganti jadi `basi`. Hook ini dirancang
tidak pernah error, supaya tidak merusak status line Claude Code.

**Batasannya:** jatah Claude dipakai bersama oleh claude.ai, aplikasi desktop Claude, dan Claude Code.
Widget hanya melihat pemakaian yang lewat Claude Code, jadi kalau kamu juga chat di claude.ai,
angka sebenarnya bisa lebih tinggi dari yang tampil.

## Susunan file

| File | Isi |
| --- | --- |
| `aiusagebar.pyw` | jendela widget, klik/seret, menu, login/logout |
| `providers.py` | pembaca data; jalankan langsung untuk melihat apa yang terbaca |
| `render.py` | semua gambar (Pillow): strip kecil dan panel detail |
| `statusline.py` | hook status line Claude Code, sumber angkanya |
| `setup.ps1` | pemasang untuk komputer baru |
| `%LOCALAPPDATA%\AIUsageBar\config.json` | posisi dan transparansi (dibuat otomatis) |

Kode untuk membaca Codex (OpenAI) dan Antigravity (Google) masih ada di `providers.py` dari versi lama,
tapi tidak ditampilkan (`READERS = (read_claude,)`).

## Kalau ada yang aneh

```powershell
python .\providers.py      # menampilkan data mentah yang terbaca
python .\aiusagebar.pyw    # jalan dengan konsol, supaya error-nya kelihatan
```

- Widget tidak muncul setelah restart: cek nilai `AIUsageBar` di `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- Angka tidak berubah: pastikan blok `statusLine` di `~\.claude\settings.json` menunjuk ke `statusline.py` di folder ini.

## Copot

Klik kanan → **Keluar**, hapus centang **Jalan saat Windows menyala** (atau hapus nilai `AIUsageBar` di key `Run`),
hapus blok `statusLine` dari `~\.claude\settings.json`, lalu hapus foldernya dan `%LOCALAPPDATA%\AIUsageBar`.

---

Proyek pribadi, tidak berafiliasi dengan Anthropic. "Claude" dan "Claude Code" adalah merek Anthropic.
