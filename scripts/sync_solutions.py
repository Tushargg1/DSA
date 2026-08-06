#!/usr/bin/env python3
"""Export first-time accepted tracker submissions into date-wise Markdown logs."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
PAGE_SIZE = 100


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not configured")
    return value


def request_json(url: str, *, method: str = "GET", payload=None, token=None):
    headers = {"Accept": "application/json", "User-Agent": "dsa-daily-sync/1.0"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Tracker request failed with HTTP {error.code}: {detail}") from error


def tracker_login(base_url: str):
    return request_json(
        f"{base_url}/auth/login",
        method="POST",
        payload={"email": require_env("TRACKER_EMAIL"), "password": require_env("TRACKER_PASSWORD")},
    )


def fetch_submissions(base_url: str, user_id: int, token: str):
    submissions = []
    page = 0
    while True:
        query = urllib.parse.urlencode({
            "page": page, "size": PAGE_SIZE, "sort": "solvedAtUtc,desc",
        })
        result = request_json(f"{base_url}/users/{user_id}/submissions?{query}", token=token)
        submissions.extend(result.get("content", []))
        if result.get("last", True):
            return submissions
        page += 1
        if page >= 1000:
            raise RuntimeError("Submission pagination exceeded the safety limit")


def parse_solved_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def markdown_text(value) -> str:
    if value is None or value == "":
        return "Not available"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def problem_url(submission: dict) -> str:
    platform = (submission.get("platform") or "").upper()
    problem_id = str(submission.get("problemId") or "").strip()
    encoded = urllib.parse.quote(problem_id, safe="")
    if platform == "LEETCODE":
        return f"https://leetcode.com/problems/{encoded}/"
    if platform == "CODEFORCES":
        match = re.fullmatch(r"(\d+)(.+)", problem_id)
        if match:
            return f"https://codeforces.com/problemset/problem/{match.group(1)}/{urllib.parse.quote(match.group(2), safe='')}"
    if platform == "GFG":
        return f"https://www.geeksforgeeks.org/problems/{encoded}/1"
    return ""


def render_day(day: str, submissions: list[dict]) -> str:
    title = datetime.strptime(day, "%Y-%m-%d").strftime("%d %B %Y")
    lines = [
        f"# DSA Solutions — {title}",
        "",
        f"**Problems solved:** {len(submissions)}",
        "",
        "| Platform | Problem | Difficulty | Tags | Solved at (IST) |",
        "|---|---|---|---|---|",
    ]
    for submission in sorted(submissions, key=lambda item: item.get("solvedAtUtc", "")):
        name = markdown_text(submission.get("problemName") or submission.get("problemId") or "Untitled")
        url = problem_url(submission)
        problem = f"[{name}]({url})" if url else name
        tags = submission.get("tags") or []
        solved_at = parse_solved_at(submission["solvedAtUtc"]).strftime("%I:%M %p")
        lines.append(
            f"| {markdown_text(submission.get('platform'))} | {problem} | "
            f"{markdown_text(submission.get('difficulty'))} | {markdown_text(', '.join(tags))} | {solved_at} |"
        )
    lines.extend(["", "_Generated automatically from accepted submissions recorded by DSA Tracker._", ""])
    return "\n".join(lines)


def write_logs(submissions: list[dict]) -> int:
    grouped = defaultdict(list)
    seen = set()
    for submission in submissions:
        if not submission.get("isFirstAttempt") or not submission.get("solvedAtUtc"):
            continue
        key = (
            submission.get("platform"), submission.get("problemId"), submission.get("solvedAtUtc")
        )
        if key in seen:
            continue
        seen.add(key)
        grouped[parse_solved_at(submission["solvedAtUtc"]).date().isoformat()].append(submission)

    changed = 0
    for day, day_submissions in grouped.items():
        destination = ROOT / "solutions" / day[:4] / day[5:7] / f"{day}.md"
        content = render_day(day, day_submissions)
        if destination.exists() and destination.read_text(encoding="utf-8") == content:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
        changed += 1
    return changed


def main() -> int:
    base_url = os.environ.get(
        "TRACKER_API_URL", "https://dsa-estimators-1.onrender.com/api"
    ).strip().rstrip("/")
    if not base_url.startswith("https://"):
        raise RuntimeError("TRACKER_API_URL must use HTTPS")
    auth = tracker_login(base_url)
    user = auth.get("user") or {}
    token = auth.get("token")
    if not user.get("id") or not token:
        raise RuntimeError("Tracker login response did not include a user and token")
    submissions = fetch_submissions(base_url, user["id"], token)
    changed = write_logs(submissions)
    print(f"Processed {len(submissions)} submissions; updated {changed} daily log(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # concise output; credentials are never printed
        print(f"Daily sync failed: {error}", file=sys.stderr)
        sys.exit(1)
