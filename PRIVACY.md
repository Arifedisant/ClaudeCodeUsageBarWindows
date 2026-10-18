# Privacy policy: AI Usage Bar

*Last updated: 18 October 2026. Publisher: XCALT.*

AI Usage Bar shows how much of your Claude Code allowance you have used, in the
Windows taskbar. It does not collect, send or sell any data.

**What the app reads, on your own computer only**

- `%USERPROFILE%\.claude.json`: the e-mail address and plan of the Claude account
  that is signed in to Claude Code, shown in the app's panel.
- `%USERPROFILE%\.claude\usage-state.json`: the usage percentages and reset times
  written by the app's own status line hook.
- Whether `%USERPROFILE%\.claude\.credentials.json` exists (used only as a
  signed-in flag; its contents are never read).

**What the app writes**

- Its own settings (position, opacity, account labels) in the app's local
  data folder.
- Only when you choose **Connect to Claude Code**: a copy of its status line
  hook in `%USERPROFILE%\.claude\ai-usage-bar\` and the `statusLine` entry in
  `%USERPROFILE%\.claude\settings.json`. A status line you had before is kept
  and restored when you choose **Disconnect from Claude Code**.

**Network**

The app makes no network connections. "Login" and "Logout" open a terminal
running Claude Code's own `claude auth` commands.

**Contact**

Questions: open an issue at
<https://github.com/Arifedisant/ClaudeCodeUsageBarWindows/issues>.

---

## Kebijakan privasi: AI Usage Bar

AI Usage Bar menampilkan pemakaian jatah Claude Code di taskbar Windows.
Aplikasi ini tidak mengumpulkan, mengirim, atau menjual data apa pun.

- **Yang dibaca (hanya di komputer sendiri):** e-mail dan paket akun Claude dari
  `.claude.json`, persentase pemakaian dari `.claude\usage-state.json`, dan ada
  atau tidaknya `.claude\.credentials.json` (isinya tidak pernah dibaca).
- **Yang ditulis:** pengaturan aplikasi sendiri; dan hanya bila memilih
  **Sambungkan ke Claude Code**, salinan hook status line di
  `.claude\ai-usage-bar\` serta entri `statusLine` di `.claude\settings.json`
  (status line lama disimpan dan dikembalikan saat diputuskan).
- **Jaringan:** aplikasi tidak membuat koneksi internet.
- **Kontak:** buka issue di tautan GitHub di atas.
