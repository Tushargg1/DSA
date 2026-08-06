# DSA Solutions by Topic

Accepted problems tracked by DSA Evaluator are organized as:

```text
topics/<topic>/<problem>/README.md
```

Each metadata file includes the problem link, platform, difficulty, tags, and first-accepted time. The sync uses the same pattern catalog as DSA Evaluator and runs daily at **12:15 AM IST**.

## Source code capture

LeetCode’s public submission feed does **not** expose private submitted source code. Therefore the scheduled metadata workflow cannot recover code for older submissions.

Actual code must be captured in the browser when a submission becomes accepted. DSA Evaluator already includes a Chrome/Edge extension for this, but its GitHub export requires the backend GitHub App configuration shown on the app’s GitHub page. After that setup:

1. Connect the `Tushargg1/DSA` repository in DSA Evaluator.
2. Generate an extension token.
3. Load the tracker repository’s `extension/` directory using Chrome/Edge **Load unpacked**.
4. Save the production API URL and extension token in the extension.
5. Submit on LeetCode; accepted source is captured and exported under its DSA pattern.

Never paste a GitHub private key, tracker password, extension token, or browser cookie into this repository.

## Workflow configuration

The GitHub Actions repository secrets `TRACKER_EMAIL` and `TRACKER_PASSWORD` authenticate the metadata sync. The API defaults to `https://dsa-estimators-1.onrender.com/api`; an Actions variable named `TRACKER_API_URL` can override it.

Automation commits use `168968951+Tushargg1@users.noreply.github.com` so commits on `main` can be attributed to the `Tushargg1` contribution graph.
