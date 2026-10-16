# Net Speed Bar

Kecepatan upload/download di taskbar Windows 11, satu gaya dengan AIUsageBar.

- Jalankan: `"C:\Program Files\Python313\pythonw.exe" netspeedbar.pyw` (butuh `psutil`, `Pillow`)
- Autostart: `HKCU\...\CurrentVersion\Run` value `NetSpeedBar` (bisa dimatikan dari klik kanan)
- Klik = panel detail (grafik 60 detik, puncak, total hari ini). Seret = pindah. Klik kanan = satuan bit/byte, transparansi, autostart, keluar.
- Config + total harian: `%LOCALAPPDATA%\NetSpeedBar\config.json`
- Hanya adapter fisik yang dihitung; ZeroTier, vEthernet, VPN, loopback dll. dikecualikan (`SKIP_WORDS`) supaya trafik tidak terhitung dua kali.
- Hanya satu instance (mutex `Local\NetSpeedBar-single`).
