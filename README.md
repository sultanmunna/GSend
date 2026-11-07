# Gmail Tray Notifier

Android-style Gmail notifications for Windows. A tiny app that lives in the
system tray, checks your Gmail every 45 seconds and shows a Windows toast when
new mail arrives — sender, subject, a short preview and which account received
it. Clicking the toast opens that mail in your browser.

**Everything runs on your PC.** There is no server, no account with us, no
telemetry. The app talks only to Google, with a read-only permission.

---

## What it does

- A tray icon with the 3 latest mails in its right-click menu (unread mails
  marked with ●) and the newest mail in the hover tooltip.
- One toast per new mail; a burst collapses into a single "{n} new mails"
  summary toast.
- Multiple Gmail accounts, side by side; every mail shows which account got it.
- Clicking a toast or menu item opens that mail in your default browser, in the
  right account.
- "Check now" in the menu polls immediately.

## Install

1. Get the `GmailNotifier` folder (from the release or your build — see
   `docs/BUILD.md` if you build it yourself) and put it anywhere, e.g.
   `%LOCALAPPDATA%\Programs\GmailNotifier`.
2. Start `GmailNotifier.exe`. Optionally pin the tray icon (Windows 11 may hide
   new tray icons in the overflow area — drag it onto the taskbar once).

There is no installer required; the optional Inno Setup installer installs
per-user (no admin rights).

## First sign-in

1. On first start your browser opens Google's account chooser.
2. Pick the account, then click **Allow**.
3. Because the app is not verified by Google yet, Google shows a
   **"Google hasn't verified this app"** warning screen. This is expected:

   > [screenshot placeholder: unverified-app warning screen]
   > Click **Advanced**, then **Go to Gmail Tray Notifier (unsafe)**, then
   > **Allow** on the permission screen.

   The app only ever asks for **read-only** access to notice new mail. It
   cannot read full message bodies, send, delete or change anything.
4. You can close the browser tab afterwards. A welcome toast confirms sign-in.

Add more accounts any time: right-click the tray icon → **Accounts ▸ Add
account…**.

## Settings

Right-click the tray icon → **Settings**:

| Setting | Meaning |
|---|---|
| Show message preview | Toast body includes a short snippet (turn off on shared PCs) |
| Primary tab only | Only notify for mail in the Primary tab (default, like the phone app) |
| Start with Windows | Registers the app in the Run key after the first account is added |

Settings live in `%APPDATA%\GmailNotifier\settings.json` — the tray menu's
**Open data folder** opens that folder.

## Privacy

- Mail content (sender, subject, preview) exists **only in memory** while the
  app runs. Nothing is written to disk except settings, your account list
  (emails only) and logs that contain no mail content.
- The only stored secret is the **refresh token**, held by Windows Credential
  Manager (protected with your Windows login via DPAPI).
- The app contacts only `accounts.google.com`, `oauth2.googleapis.com` and
  `gmail.googleapis.com`. No analytics, no update checks, nothing else.
- Toasts remain in the Windows Action Center — use "Show message preview: off"
  on shared machines.
- Removing an account (Accounts ▸ [account] ▸ Remove) deletes the token from
  Credential Manager and revokes it at Google.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Google hasn't verified this app" | Expected; see First sign-in above. |
| Error 403 `access_denied` at sign-in | Your address is not a test user of the developer's Cloud project (developer task, `docs/GOOGLE_CLOUD_SETUP.md`). |
| "Sign-in needed" toast / ⚠ in the menu | The token expired or was revoked. Accounts ▸ [account] ▸ **Sign in again**. |
| No toasts at all | Check Focus Assist / Do Not Disturb; check Settings ▸ Primary tab only (Promotions/Social are skipped when on). |
| Mail arrives late | Notification delay is up to one poll interval (45 s by default). |
| Icon missing after reboot | Re-pin it once in the tray overflow; check Settings ▸ Start with Windows. |

## Uninstall

1. Right-click the tray icon → **Accounts ▸ [each account] ▸ Remove** (this
   deletes and revokes the stored tokens).
2. Quit from the tray menu.
3. Delete the app folder, plus `%APPDATA%\GmailNotifier` and
   `%LOCALAPPDATA%\GmailNotifier` if you want the settings and logs gone too.
4. If you used the installer, uninstall from Windows "Installed apps".

## For developers

- Development, architecture and security rules: start at `AGENTS.md`.
- Milestones, docs and the test strategy live in `docs/`.
- Build the exe with `.\scripts\build_exe.ps1` — see `docs/BUILD.md`.
