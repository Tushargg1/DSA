#!/usr/bin/env python3
"""Export first-time accepted tracker submissions into topic/problem metadata."""

import json
import os
import re
import shutil
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


def safe_slug(value) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:100].rstrip("-") or "uncategorized"


def problem_url(submission: dict) -> str:
    platform = (submission.get("platform") or "").upper()
    problem_id = str(submission.get("problemId") or "").strip()
    encoded = urllib.parse.quote(problem_id, safe="")
    if platform == "LEETCODE":
        return f"https://leetcode.com/problems/{encoded}/"
    if platform == "CODEFORCES":
        match = re.fullmatch(r"(\d+)(.+)", problem_id)
        if match:
            suffix = urllib.parse.quote(match.group(2), safe="")
            return f"https://codeforces.com/problemset/problem/{match.group(1)}/{suffix}"
    if platform == "GFG":
        return f"https://www.geeksforgeeks.org/problems/{encoded}/1"
    return ""


def fetch_catalog(base_url: str, token: str) -> dict:
    snapshot = request_json(f"{base_url}/catalog", token=token)
    index = {}
    for question in snapshot.get("questions", []):
        slug = safe_slug(question.get("slug"))
        patterns = question.get("patterns") or question.get("pattern") or []
        index[slug] = {
            "topic": safe_slug(patterns[0]) if patterns else "uncategorized",
            "difficulty": question.get("difficulty"),
        }
    return index


def infer_topic(submission: dict, catalog: dict) -> tuple[str, str | None]:
    problem_id = safe_slug(submission.get("problemId"))
    catalog_entry = catalog.get(problem_id, {})
    topic = catalog_entry.get("topic")
    if topic and topic != "uncategorized":
        return topic, catalog_entry.get("difficulty")

    tags = submission.get("tags") or []
    if tags:
        return safe_slug(tags[0]), catalog_entry.get("difficulty")

    title = str(submission.get("problemName") or "").lower()
    title_topics = (
        (("linked list", "linked-list"),),
        (("stack", "stack"),),
        (("queue", "queue"),),
        (("tree", "trees"),),
        (("graph", "graphs"),),
        (("array", "arrays"),),
        (("string", "strings"),),
        (("binary search", "binary-search"),),
        (("subsequence", "dynamic-programming"),),
    )
    for ((keyword, fallback_topic),) in title_topics:
        if keyword in title:
            return fallback_topic, catalog_entry.get("difficulty")
    if "next greater" in title:
        return "stack", catalog_entry.get("difficulty")
    return "uncategorized", catalog_entry.get("difficulty")


def render_problem(submission: dict, topic: str, catalog_difficulty) -> str:
    name = markdown_text(submission.get("problemName") or submission.get("problemId") or "Untitled")
    url = problem_url(submission)
    platform = markdown_text(submission.get("platform"))
    difficulty = markdown_text(submission.get("difficulty") or catalog_difficulty)
    tags = markdown_text(", ".join(submission.get("tags") or []))
    solved_at = parse_solved_at(submission["solvedAtUtc"]).strftime("%d %B %Y, %I:%M %p IST")
    lines = [
        f"# {name}", "",
        f"- **Topic:** {markdown_text(topic.replace('-', ' ').title())}",
        f"- **Platform:** {platform}",
        f"- **Difficulty:** {difficulty}",
        f"- **Tags:** {tags}",
        f"- **First accepted:** {solved_at}",
    ]
    if url:
        lines.append(f"- **Problem:** [{name}]({url})")
    lines.extend([
        "", "## Solution source", "",
        "> Source code was not present in the tracker submission feed. The DSA Solution Capture browser extension must be configured before an accepted submission to archive code automatically.",
        "",
    ])
    return "\n".join(lines)


def write_topics(submissions: list[dict], catalog: dict) -> int:
    legacy = ROOT / "solutions"
    if legacy.exists():
        shutil.rmtree(legacy)

    changed = 0
    seen = set()
    for submission in sorted(submissions, key=lambda item: item.get("solvedAtUtc", "")):
        if not submission.get("isFirstAttempt") or not submission.get("solvedAtUtc"):
            continue
        key = (submission.get("platform"), submission.get("problemId"))
        if key in seen:
            continue
        seen.add(key)
        topic, catalog_difficulty = infer_topic(submission, catalog)
        problem = safe_slug(submission.get("problemId") or submission.get("problemName"))
        destination = ROOT / "topics" / topic / problem / "README.md"
        content = render_problem(submission, topic, catalog_difficulty)
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
    catalog = fetch_catalog(base_url, token)
    changed = write_topics(submissions, catalog)
    print(f"Processed {len(submissions)} submissions; updated {changed} topic record(s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # concise output; credentials are never printed
        print(f"Topic sync failed: {error}", file=sys.stderr)
        sys.exit(1)
