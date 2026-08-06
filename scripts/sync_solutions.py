#!/usr/bin/env python3
"""Export first-time accepted tracker submissions into topic/problem metadata."""

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
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


def fetch_captures(base_url: str, token: str) -> list[dict]:
    return request_json(f"{base_url}/github/captures", token=token)


def parse_solved_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def markdown_text(value) -> str:
    if value is None or value == "":
        return "Not available"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def safe_slug(value) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:100].rstrip("-") or "uncategorized"


def normalize_platform(value) -> str:
    platform = str(value or "UNKNOWN").upper()
    return "GEEKSFORGEEKS" if platform == "GFG" else platform


def record_key(record: dict) -> str:
    problem_id = str(record.get("problemId") or record.get("problemName") or "").strip()
    if not problem_id:
        raise RuntimeError("A tracker record is missing its problem identity")
    return f"{normalize_platform(record.get('platform'))}:{problem_id}"


def problem_url(record: dict) -> str:
    captured_url = record.get("problemUrl")
    if captured_url:
        return captured_url
    platform = normalize_platform(record.get("platform"))
    problem_id = str(record.get("problemId") or "").strip()
    encoded = urllib.parse.quote(problem_id, safe="")
    if platform == "LEETCODE":
        return f"https://leetcode.com/problems/{encoded}/"
    if platform == "CODEFORCES":
        match = re.fullmatch(r"(\d+)[-:]?(.+)", problem_id)
        if match:
            suffix = urllib.parse.quote(match.group(2), safe="")
            return f"https://codeforces.com/problemset/problem/{match.group(1)}/{suffix}"
    if platform == "GEEKSFORGEEKS":
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


def infer_topic(record: dict, catalog: dict) -> tuple[str, str | None]:
    captured_topic = safe_slug(record.get("patternSlug"))
    if captured_topic != "uncategorized":
        return captured_topic, record.get("difficulty")

    catalog_entry = catalog.get(safe_slug(record.get("problemId")), {})
    topic = catalog_entry.get("topic")
    if topic and topic != "uncategorized":
        return topic, record.get("difficulty") or catalog_entry.get("difficulty")

    tags = record.get("tags") or []
    if tags:
        return safe_slug(tags[0]), record.get("difficulty") or catalog_entry.get("difficulty")

    title = str(record.get("problemName") or "").lower()
    rules = (
        ("linked list", "linked-list"), ("next greater", "stack"),
        ("stack", "stack"), ("queue", "queue"), ("tree", "trees"),
        ("graph", "graphs"), ("array", "arrays"), ("string", "strings"),
        ("binary search", "binary-search"),
        ("combination", "backtracking"), ("subsets", "backtracking"),
        ("parentheses", "backtracking"), ("word search", "backtracking"),
    )
    for keyword, fallback in rules:
        if keyword in title:
            return fallback, record.get("difficulty") or catalog_entry.get("difficulty")
    return "uncategorized", record.get("difficulty") or catalog_entry.get("difficulty")


def merge_records(submissions: list[dict], captures: list[dict]) -> dict[str, dict]:
    records = {}
    for submission in sorted(submissions, key=lambda item: item.get("solvedAtUtc", "")):
        if not submission.get("isFirstAttempt") or not submission.get("solvedAtUtc"):
            continue
        records.setdefault(record_key(submission), dict(submission))

    for capture in sorted(captures, key=lambda item: item.get("solvedAtUtc", "")):
        key = record_key(capture)
        current = records.get(key, {})
        merged = {**current}
        for field in (
            "platform", "problemId", "problemName", "problemUrl", "language",
            "source", "difficulty", "tags", "patternSlug",
        ):
            value = capture.get(field)
            if value is not None:
                merged[field] = value
        accepted_times = [value for value in (
            current.get("solvedAtUtc"), capture.get("solvedAtUtc")
        ) if value]
        if accepted_times:
            merged["solvedAtUtc"] = min(accepted_times)
        merged["isFirstAttempt"] = True
        records[key] = merged
    return records


def source_fence(source: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", source)), default=0)
    return "`" * max(3, longest + 1)


def language_hint(language) -> str:
    return re.sub(r"[^a-z0-9_+.#-]", "", str(language or "").lower())


def render_problem(key: str, record: dict, topic: str, catalog_difficulty) -> str:
    name = markdown_text(record.get("problemName") or record.get("problemId") or "Untitled")
    url = problem_url(record)
    difficulty = markdown_text(record.get("difficulty") or catalog_difficulty)
    tags = markdown_text(", ".join(record.get("tags") or []))
    solved_at = parse_solved_at(record["solvedAtUtc"]).strftime("%d %B %Y, %I:%M %p IST")
    lines = [
        f"# {name}", "",
        f"- **Topic:** {markdown_text(topic.replace('-', ' ').title())}",
        f"- **Platform:** {markdown_text(normalize_platform(record.get('platform')))}",
        f"- **Difficulty:** {difficulty}",
        f"- **Tags:** {tags}",
        f"- **First accepted:** {solved_at}",
    ]
    if url:
        lines.append(f"- **Problem:** [{name}]({url})")

    source = record.get("source")
    lines.extend(["", "## Solution", ""])
    if source:
        fence = source_fence(source)
        lines.extend([f"{fence}{language_hint(record.get('language'))}", source.rstrip(), fence, ""])
    else:
        lines.extend([
            "> Source has not been captured yet. Submit again with the DSA Solution Capture extension enabled to update this record.",
            "",
        ])
    lines.append(f"<!-- generated-by-dsa-sync:{key} -->")
    lines.append("")
    return "\n".join(lines)


GENERATED_MARKER = re.compile(r"<!-- generated-by-dsa-sync:(.+?) -->")
SOLUTION_BLOCK = re.compile(
    r"## Solution\s*\n\s*(?P<fence>`{3,})(?P<language>[^\n]*)\n"
    r"(?P<source>.*?)\n(?P=fence)(?:\s*\n|$)", re.DOTALL,
)


def validate_index_path(value: str) -> str:
    relative = Path(value)
    if (relative.is_absolute() or ".." in relative.parts or
            len(relative.parts) != 4 or relative.parts[0] != "topics" or
            relative.name != "README.md"):
        raise RuntimeError(f"Unsafe path in .dsa-sync-index.json: {value}")
    return relative.as_posix()


def load_index() -> dict[str, str]:
    path = ROOT / ".dsa-sync-index.json"
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(".dsa-sync-index.json is not valid JSON") from error
        if not isinstance(value, dict):
            raise RuntimeError(".dsa-sync-index.json must contain an object")
        return {str(key): validate_index_path(str(item)) for key, item in value.items()}

    discovered = {}
    for readme in ROOT.glob("topics/*/*/README.md"):
        content = readme.read_text(encoding="utf-8")
        marker = GENERATED_MARKER.search(content)
        if marker:
            key = marker.group(1).strip()
        else:
            platform_match = re.search(r"^- \*\*Platform:\*\*\s*(.+?)\s*$", content, re.MULTILINE)
            platform = normalize_platform(platform_match.group(1).replace(" ", "") if platform_match else "LEETCODE")
            key = f"{platform}:{readme.parent.name}"
        relative = readme.relative_to(ROOT).as_posix()
        if key in discovered and discovered[key] != relative:
            raise RuntimeError(f"Duplicate generated identity found while bootstrapping: {key}")
        discovered[key] = relative
    return discovered


def remove_empty_parents(path: Path) -> None:
    parent = path.parent
    topics = ROOT / "topics"
    while parent != topics and parent.is_relative_to(topics):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def collision_path(relative: Path, key: str) -> Path:
    platform = safe_slug(key.split(":", 1)[0])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    folder = f"{relative.parent.name}-{platform}-{digest}"
    return relative.parent.parent / folder / "README.md"


def plan_destinations(records: dict[str, dict], catalog: dict,
                      index: dict[str, str]) -> dict[str, tuple[str, str | None, Path]]:
    bases = {}
    for key, record in records.items():
        topic, difficulty = infer_topic(record, catalog)
        problem = safe_slug(record.get("problemId") or record.get("problemName"))
        bases[key] = (topic, difficulty, Path("topics") / topic / problem / "README.md")

    existing_owners = {}
    for owner, path in index.items():
        if path in existing_owners and existing_owners[path] != owner:
            raise RuntimeError(f"Multiple identities own generated path: {path}")
        existing_owners[path] = owner

    plans = {}
    used = set()
    for key in sorted(records):
        topic, difficulty, _ = bases[key]
        previous = index.get(key)
        if previous and Path(previous).parts[1] == topic and previous not in used:
            plans[key] = (topic, difficulty, Path(previous))
            used.add(previous)

    for key in sorted(records):
        if key in plans:
            continue
        topic, difficulty, base = bases[key]
        relative = base
        path = relative.as_posix()
        if path in used or (path in existing_owners and existing_owners[path] != key):
            relative = collision_path(base, key)
            path = relative.as_posix()
        if path in used or (path in existing_owners and existing_owners[path] != key):
            raise RuntimeError(f"Unable to generate a unique path for {key}")
        used.add(path)
        plans[key] = (topic, difficulty, relative)
    return plans


def preserve_existing_source(record: dict, existing: str | None) -> dict:
    if record.get("source") is not None or not existing:
        return record
    match = SOLUTION_BLOCK.search(existing)
    if not match:
        return record
    preserved = dict(record)
    preserved["source"] = match.group("source")
    if not preserved.get("language") and match.group("language").strip():
        preserved["language"] = match.group("language").strip()
    return preserved


def write_topics(records: dict[str, dict], catalog: dict) -> tuple[int, int, int]:
    legacy = ROOT / "solutions"
    if legacy.exists():
        shutil.rmtree(legacy)

    index = load_index()
    plans = plan_destinations(records, catalog, index)
    next_index = dict(index)
    created = updated = moved = 0
    for key in sorted(records):
        topic, catalog_difficulty, relative = plans[key]
        destination = ROOT / relative
        old_relative = index.get(key)
        old_path = ROOT / old_relative if old_relative else None

        existing = destination.read_text(encoding="utf-8") if destination.exists() else None
        previous = existing
        if previous is None and old_path is not None and old_path.exists():
            previous = old_path.read_text(encoding="utf-8")
        record = preserve_existing_source(records[key], previous)
        content = render_problem(key, record, topic, catalog_difficulty)

        if existing != content:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
            if existing is None:
                created += 1
            else:
                updated += 1

        if old_path is not None and old_path != destination and old_path.exists():
            old_path.unlink()
            remove_empty_parents(old_path)
            moved += 1
        next_index[key] = relative.as_posix()

    index_path = ROOT / ".dsa-sync-index.json"
    index_content = json.dumps(dict(sorted(next_index.items())), indent=2) + "\n"
    if not index_path.exists() or index_path.read_text(encoding="utf-8") != index_content:
        index_path.write_text(index_content, encoding="utf-8", newline="\n")
        updated += 1
    return created, updated, moved


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
    captures = fetch_captures(base_url, token)
    catalog = fetch_catalog(base_url, token)
    records = merge_records(submissions, captures)
    created, updated, moved = write_topics(records, catalog)
    print(
        f"Upserted {len(records)} distinct problems from {len(submissions)} submissions "
        f"and {len(captures)} source captures: {created} created, "
        f"{updated} updated, {moved} moved."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # credentials and source code are never printed
        print(f"Topic sync failed: {error}", file=sys.stderr)
        sys.exit(1)
