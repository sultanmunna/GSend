# GOOGLE_CLOUD_SETUP.md

One-time setup by the **developer**. End users of the finished app never do this. You create one OAuth client of type "Desktop app"; its Client ID is embedded in the app.

Google renames console screens from time to time. If a label differs, look for the nearest equivalent.

## Steps

1. Open https://console.cloud.google.com and create a project (for example `gmail-notifier`).
2. **APIs & Services → Library**, search **Gmail API**, click **Enable**.
3. Open **Google Auth Platform** (older name: OAuth consent screen) and click **Get started**:
   - App name, user support email
   - Audience: **External**
   - Contact email, agree to the policy, create
4. **Data Access → Add or remove scopes**, add `https://www.googleapis.com/auth/gmail.readonly`, save. This is a *restricted* scope, which is expected.
5. **Audience**: keep **Testing**, and under **Test users** add every Gmail address you will sign in with (up to 100).
6. **Clients → Create client**: application type **Desktop app**, name it, create.
7. Copy the **Client ID** and **Client secret**, or download the JSON.
8. Save the file as `client_config.json` in the repo root (git-ignored). Format:

```json
{
  "installed": {
    "client_id": "YOUR_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_SECRET",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost"]
  }
}
```

The JSON downloaded from the console already has this shape. Commit only `client_config.example.json` with placeholder values.

## Testing vs production

| | Testing | In production (unverified) |
|---|---|---|
| Who can sign in | Only listed test users (max 100) | Anyone, up to 100 users, after a warning screen |
| Refresh token lifetime | Expires after 7 days | Does not expire weekly |
| Warning screen | Yes ("Google hasn't verified this app") | Yes |
| Good for | Development | Daily personal use |

For daily personal use, press **Publish app** on the Audience page. Sharing the app widely would require Google verification for the restricted Gmail scope, which can include a paid security assessment. Check Google's current "restricted scope verification" documentation before planning a public release.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| **"Publish app" button is disabled** on the Audience page | The Branding page is incomplete. Open **Auth Platform → Branding** and fill every required field: app name, user support email, home page URL, privacy policy URL, developer contact. For a personal app without a website, your GitHub repo URL works for both links. Save, reload the Audience page (Ctrl+F5). If it is still disabled with every Branding checkmark green, it is a known console bug — retry in an incognito window or another browser. |
| `Error 403: access_denied` ("not completed the verification") | The Gmail address is not a test user. Add it under Audience. |
| `redirect_uri_mismatch` | The client type is not **Desktop app**. Create a new Desktop client. |
| "Google hasn't verified this app" screen | Expected. Click **Advanced → Go to (app)**. |
| `invalid_grant` after about a week | Testing mode token expiry. Publish the app, then sign in again. |
| `invalid_grant` any time | The user revoked access or changed their Google password. Sign in again. |
| `403 accessNotConfigured` / "API has not been used" | The Gmail API is not enabled in this project (step 2). |
| No refresh token returned | Make sure `prompt=consent` is sent and `access_type=offline` is used (the library default). |
