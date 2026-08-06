# DSA Solution Capture

A Chrome/Edge extension that captures source after an accepted submission and sends it to DSA Evaluator.

## Install

1. Download or clone this repository.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable **Developer mode**.
4. Click **Load unpacked** and select this `extension/` directory.
5. In DSA Evaluator, open **GitHub** and click **Generate capture token**.
6. Enter the API URL shown there and the one-time token in the extension popup.

Captures are sent to `{apiBaseUrl}/github/captures` using `X-DSA-Extension-Token`.

## Supported sites

- LeetCode problem pages
- Codeforces problemset and contest pages
- GeeksforGeeks practice problem pages

## Security and limitations

- The API URL and token stay in `chrome.storage.local`; no credentials are included in this repository.
- Requests omit browser credentials, cookies, and coding-platform session data.
- Host access is limited to the supported coding sites, the production DSA Evaluator API, and the localhost development API.
- Source extraction and accepted-result detection are best-effort because third-party page markup can change.
- Use HTTPS for production. HTTP is accepted only for local development.
- A source hash prevents an identical accepted solution from being sent repeatedly; changed source is sent and updates the same problem record.
