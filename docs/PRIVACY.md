# Privacy Policy — Gmail Tray Notifier

Last updated: November 7, 2026

Gmail Tray Notifier ("the app") is a free Windows tray application that shows desktop notifications for new Gmail messages. It is developed and maintained by Sultan Mahmud Munna. This policy describes what the app accesses, what it stores, and what it never does — in short: **everything stays on your PC.**

## What the app accesses

With your Google permission, the app reads basic metadata of your recent inbox messages through Google's Gmail API, using the single read-only scope `https://www.googleapis.com/auth/gmail.readonly`. This means it can display the sender, subject, a short snippet and the timestamp of recent messages. It **cannot** send, modify, delete or move mail, and it cannot read attachments or full message bodies.

## What the app stores on your PC

- A Google OAuth **refresh token**, stored only in **Windows Credential Manager** (encrypted by Windows).
- App settings and your account email addresses and labels, stored in `%LOCALAPPDATA%\GmailNotifier` on your PC.
- A local log file containing technical events only — never mail content, subjects, senders or tokens.

## What the app never does

- No server and no cloud storage — the app has no backend.
- No analytics, telemetry, crash reporting or advertising.
- Mail content (sender, subject, snippet, message IDs) is kept in memory only and is never written to disk, logs or the clipboard, and never sent anywhere.
- Your data is never sold, shared or transferred — there is no one to share it with.

## Data sharing and Google API disclosure

The app communicates only with Google's OAuth and Gmail API endpoints (`accounts.google.com`, `oauth2.googleapis.com`, `gmail.googleapis.com`). Gmail Tray Notifier's use and transfer to any other app of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Deleting your data

- Choose **Remove** under the Accounts menu, or uninstall the app: the refresh token is deleted from Windows Credential Manager.
- Revoke the app's access at any time at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- The local data folder `%LOCALAPPDATA%\GmailNotifier` can be deleted to remove all remaining traces.

## Changes

If the app's data handling ever changes, this policy will be updated and the "last updated" date above will reflect it.

## Contact

Questions or requests: **[YOUR-EMAIL]@gmail.com**
