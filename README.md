# Topic-wise DSA Solution Archive

Every distinct accepted problem is stored once at:

```text
topics/<topic>/<problem>/README.md
```

## Create-or-update behavior

The `DSA solution upsert` workflow runs approximately every five minutes:

1. Logs in to DSA Evaluator with encrypted Actions secrets.
2. Reads every first-time accepted submission and every browser source capture.
3. Uses `platform + problem ID` as the stable identity.
4. Creates a missing problem file.
5. Updates the same file when metadata, topic, language, or source changes.
6. Makes no commit when the generated content is unchanged.
7. Moves the file and removes the old generated path if its topic changes.

The `.dsa-sync-index.json` manifest keeps paths stable and prevents duplicates.

## Capturing actual source code

Public LeetCode/Codeforces/GFG submission feeds do not expose private source. Install this repository's `extension/` directory as an unpacked Chrome/Edge extension. In DSA Evaluator's **GitHub** page:

1. Click **Generate capture token**.
2. Copy the displayed production API URL and token into the extension.
3. Keep the extension enabled when submitting.

When an accepted result appears, the extension sends the source to your authenticated tracker account. A first capture creates the problem record; a later accepted submission for the same problem updates its source.

Previously accepted source cannot be reconstructed automatically. Open the old accepted submission on the coding platform and submit it again with the extension enabled if you want that exact code archived.

## Repository automation

Required Actions secrets:

- `TRACKER_EMAIL`
- `TRACKER_PASSWORD`

The workflow defaults to `https://dsa-estimators-1.onrender.com/api`. Set the `TRACKER_API_URL` repository variable only if that production URL changes.

Automation commits use `168968951+Tushargg1@users.noreply.github.com` for contribution attribution.
