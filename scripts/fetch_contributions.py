#!/usr/bin/env python3
"""Refresh data/contributions.json from GitHub.

The renderer only reads JSON. This script is the only piece that talks to
GitHub, so the scheduled Action can refresh the data without touching the
card markup.

Only public repositories owned by the profile account are collected. The
repository list is ordered by most recent push so the cards change when a
new public repo appears or an existing one is updated.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "profile.json"
OUT_PATH = ROOT / "data" / "contributions.json"

PROFILE_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    name
    repositories(
      first: 100
      privacy: PUBLIC
      ownerAffiliations: OWNER
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      totalCount
      nodes {
        name
        description
        url
        stargazerCount
        forkCount
        pushedAt
        isFork
        primaryLanguage {
          name
          color
        }
      }
    }
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            weekday
          }
        }
      }
    }
  }
}
"""


def token() -> str:
    value = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if value:
        return value.strip()
    try:
        return subprocess.check_output(
            ["gh", "auth", "token"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "No GitHub token found. Set GH_TOKEN/GITHUB_TOKEN or run `gh auth login`."
        )


def request_json(url: str, auth: str, payload: dict | None = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {auth}",
        "User-Agent": "theanugrahh-profile-cards",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def graphql(query: str, variables: dict, auth: str) -> dict:
    result = request_json(
        "https://api.github.com/graphql",
        auth,
        {"query": query, "variables": variables},
    )
    if result.get("errors"):
        messages = "; ".join(error.get("message", "unknown") for error in result["errors"])
        raise SystemExit(f"GitHub GraphQL error: {messages}")
    return result["data"]


def month_keys(last: date, count: int = 12) -> list[str]:
    keys = []
    year, month = last.year, last.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(keys))


def level_for(count: int, peak: int) -> int:
    if count <= 0:
        return 0
    if peak <= 1:
        return 4
    return max(1, min(4, math.ceil(count / peak * 4)))


def public_repos(user: dict, login: str) -> list[dict]:
    nodes = (user.get("repositories") or {}).get("nodes") or []
    repos = []
    for node in nodes:
        language = node.get("primaryLanguage") or {}
        name = node.get("name") or ""
        repos.append(
            {
                "name": name,
                "description": node.get("description") or "",
                "language": language.get("name") or "",
                "language_color": language.get("color") or "",
                "stars": int(node.get("stargazerCount") or 0),
                "forks": int(node.get("forkCount") or 0),
                "url": node.get("url") or f"https://github.com/{login}/{name}",
                "updated": (node.get("pushedAt") or "")[:10],
                "pushed_at": node.get("pushedAt") or "",
                "is_fork": bool(node.get("isFork")),
            }
        )
    return repos


def language_counts(repos: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for repo in repos:
        name = repo["language"] or "Other"
        counts[name] = counts.get(name, 0) + 1
    languages = [{"name": name, "count": count} for name, count in counts.items()]
    languages.sort(key=lambda item: (-item["count"], item["name"].lower()))
    return languages


def main() -> int:
    if not PROFILE_PATH.exists():
        raise SystemExit(f"Missing {PROFILE_PATH}")
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    login = os.environ.get("PROFILE_LOGIN") or profile.get("login", "theanugrahh")
    auth = token()

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    data = graphql(
        PROFILE_QUERY,
        {
            "login": login,
            "from": f"{start.isoformat()}T00:00:00Z",
            "to": f"{today.isoformat()}T23:59:59Z",
        },
        auth,
    )
    user = data["user"]
    calendar = user["contributionsCollection"]["contributionCalendar"]

    days = []
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            days.append(
                {
                    "date": day["date"],
                    "count": int(day["contributionCount"]),
                    "weekday": int(day["weekday"]),
                }
            )
    days.sort(key=lambda item: item["date"])
    if not days:
        raise SystemExit("GitHub returned an empty contribution calendar.")

    peak = max((item["count"] for item in days), default=0)
    for item in days:
        item["level"] = level_for(item["count"], peak)

    by_month: dict[str, int] = {}
    for item in days:
        by_month[item["date"][:7]] = by_month.get(item["date"][:7], 0) + item["count"]

    last_day = date.fromisoformat(days[-1]["date"])
    months = [
        {
            "key": key,
            "label": date.fromisoformat(f"{key}-01").strftime("%b").upper(),
            "count": by_month.get(key, 0),
        }
        for key in month_keys(last_day)
    ]

    current_streak = 0
    for item in reversed(days):
        if item["count"] > 0:
            current_streak += 1
        else:
            break

    longest_streak = 0
    running = 0
    for item in days:
        if item["count"] > 0:
            running += 1
            longest_streak = max(longest_streak, running)
        else:
            running = 0

    busiest = max(days, key=lambda item: (item["count"], item["date"]))
    active_days = sum(1 for item in days if item["count"] > 0)

    repos = public_repos(user, login)
    languages = language_counts(repos)
    named_languages = [item for item in languages if item["name"] != "Other"]
    last_push = repos[0]["updated"] if repos else ""
    stars = sum(repo["stars"] for repo in repos)
    forks = sum(repo["forks"] for repo in repos)

    output = {
        "generated_at": datetime.now(timezone.utc).date().isoformat(),
        "login": login,
        "public_repos": int((user.get("repositories") or {}).get("totalCount") or 0),
        "window": {"from": days[0]["date"], "to": days[-1]["date"]},
        "stats": {
            "total_contributions": int(calendar.get("totalContributions") or 0),
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "active_days": active_days,
            "tracked_days": len(days),
            "busiest_day": busiest,
            "peak": peak,
            "language_count": len(named_languages),
            "stars": stars,
            "forks": forks,
            "last_push": last_push,
        },
        "months": months,
        "days": days,
        "languages": languages,
        "repos": repos,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {OUT_PATH.relative_to(ROOT)} · "
        f"{output['public_repos']} public repos · "
        f"{len(languages)} language groups · "
        f"{output['stats']['total_contributions']} contributions · "
        f"{active_days} active days"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
