#!/usr/bin/env python3
"""Post CodeRev findings as inline GitHub PR review comments.

Uses only stdlib — no requests, no PyGithub — for maximum CI portability.

Usage:
    python post_review_comments.py \
        --result review_result.json \
        --pr 42 \
        --repo owner/repo \
        --sha abc1234
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


def github_api(method: str, path: str, body: dict | None = None) -> dict | list:
    """Make a GitHub API request using only stdlib."""
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com{path}"

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "CodeRev/0.3.0",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read()
            return json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"GitHub API error {e.code}: {body_text}", file=sys.stderr)
        return {}


def build_position_map(diff_text: str) -> dict[tuple[str, int], int]:
    """Map (file_path, line_number) -> diff_position for inline comments."""
    position_map: dict[tuple[str, int], int] = {}
    current_file: str | None = None
    diff_position = 0
    current_file_line = 0

    for line in diff_text.split("\n"):
        file_match = re.match(r"^\+\+\+ b/(.+)$", line)
        if file_match:
            current_file = file_match.group(1)
            diff_position += 1
            continue

        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_file_line = int(hunk_match.group(1)) - 1
            diff_position += 1
            continue

        if current_file is None:
            diff_position += 1
            continue

        if line.startswith("+"):
            current_file_line += 1
            diff_position += 1
            position_map[(current_file, current_file_line)] = diff_position
        elif line.startswith("-"):
            diff_position += 1
        elif line.startswith(" "):
            current_file_line += 1
            diff_position += 1
            position_map[(current_file, current_file_line)] = diff_position
        elif line.startswith("diff ") or line.startswith("index ") or line.startswith("---"):
            diff_position += 1

    return position_map


def severity_emoji(severity: str) -> str:
    return {
        "critical": "\U0001f534",
        "high": "\U0001f7e1",
        "medium": "\U0001f7e0",
        "low": "\U0001f535",
        "info": "\u26aa",
    }.get(severity, "\u26aa")


def format_comment(finding: dict) -> str:
    """Format a finding as a GitHub inline comment body."""
    emoji = severity_emoji(finding["severity"])
    category = finding.get("category", "")
    refs = finding.get("references", [])
    fix = finding.get("suggested_fix", "")
    confidence = finding.get("confidence", 0)

    lines = [
        f"{emoji} **CodeRev [{finding['severity'].upper()}]** \u2014 {finding['title']}",
        "",
        finding["description"],
    ]

    if fix:
        lines += [
            "",
            "**Suggested fix:**",
            "```python",
            fix,
            "```",
        ]

    if refs:
        lines += ["", f"**References:** {' \u00b7 '.join(refs)}"]

    lines += ["", f"_Confidence: {confidence:.0%} \u00b7 Category: {category}_"]
    lines += [f"<!-- coderev-finding:{finding.get('id', '')} -->"]

    return "\n".join(lines)


def delete_existing_coderev_comments(repo: str, pr: int) -> None:
    """Delete previous CodeRev inline review comments to avoid duplicates."""
    owner, name = repo.split("/")

    comments = github_api("GET", f"/repos/{owner}/{name}/pulls/{pr}/comments")
    if not isinstance(comments, list):
        return

    for comment in comments:
        if "<!-- coderev-finding:" in comment.get("body", ""):
            github_api(
                "DELETE",
                f"/repos/{owner}/{name}/pulls/comments/{comment['id']}",
            )
            time.sleep(0.1)


def dismiss_existing_coderev_reviews(repo: str, pr: int) -> None:
    """Dismiss previous REQUEST_CHANGES reviews from the bot.

    Without this, a stale REQUEST_CHANGES review blocks the PR even after
    the critical finding is fixed and the new review posts as COMMENT.
    """
    owner, name = repo.split("/")
    reviews = github_api("GET", f"/repos/{owner}/{name}/pulls/{pr}/reviews")
    if not isinstance(reviews, list):
        return

    for review in reviews:
        if (
            review.get("state") == "CHANGES_REQUESTED"
            and review.get("body", "").startswith("<!-- coderev-review -->")
        ):
            github_api(
                "PUT",
                f"/repos/{owner}/{name}/pulls/{pr}/reviews/{review['id']}/dismissals",
                {"message": "CodeRev re-review in progress"},
            )


def post_review(
    repo: str, pr: int, sha: str, diff_text: str, result: dict
) -> None:
    """Post all findings as a single GitHub pull request review."""
    owner, name = repo.split("/")
    position_map = build_position_map(diff_text)
    findings = result.get("findings", [])

    inline_comments = []
    unmapped_count = 0

    for finding in findings:
        file_path = finding.get("file_path", "")
        line_range = finding.get("line_range")

        if not line_range:
            unmapped_count += 1
            continue

        start_line = line_range.get("start", 1)
        position = position_map.get((file_path, start_line))

        if position is None:
            for offset in [1, -1, 2, -2, 3, -3]:
                position = position_map.get((file_path, start_line + offset))
                if position:
                    break

        if position is None:
            unmapped_count += 1
            print(
                f"  Warning: Could not map {file_path}:{start_line} to diff position "
                "- will appear in summary only",
                file=sys.stderr,
            )
            continue

        inline_comments.append(
            {
                "path": file_path,
                "position": position,
                "body": format_comment(finding),
            }
        )

    if not inline_comments:
        print(
            f"No findings could be mapped to diff positions ({unmapped_count} unmapped)"
        )
        return

    has_critical = any(f.get("severity") == "critical" for f in findings)
    event = "REQUEST_CHANGES" if has_critical else "COMMENT"

    review_body = {
        "commit_id": sha,
        "body": (
            f"<!-- coderev-review -->\n"
            f"**CodeRev** found {len(findings)} issue(s). "
            f"Inline comments mark the specific locations."
        ),
        "event": event,
        "comments": inline_comments,
    }

    response = github_api(
        "POST",
        f"/repos/{owner}/{name}/pulls/{pr}/reviews",
        review_body,
    )

    if response:
        print(
            f"Posted {len(inline_comments)} inline comment(s) "
            f"({unmapped_count} could not be mapped to diff positions)"
        )
    else:
        print("Failed to post review comments", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post CodeRev findings as PR comments"
    )
    parser.add_argument("--result", required=True, help="Path to review_result.json")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--repo", required=True, help="Repository (owner/repo)")
    parser.add_argument("--sha", required=True, help="Head commit SHA")
    parser.add_argument("--diff", default="pr.patch", help="Path to diff file")
    args = parser.parse_args()

    try:
        with open(args.result) as f:
            result = json.load(f)
    except FileNotFoundError:
        print(f"Review result not found: {args.result}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.diff) as f:
            diff_text = f.read()
    except FileNotFoundError:
        print(f"Diff file not found: {args.diff}", file=sys.stderr)
        sys.exit(1)

    if not result.get("findings"):
        print("No findings to post")
        return

    print("Cleaning up previous CodeRev comments...")
    delete_existing_coderev_comments(args.repo, args.pr)

    print("Dismissing stale REQUEST_CHANGES reviews...")
    dismiss_existing_coderev_reviews(args.repo, args.pr)

    print(f"Posting {len(result['findings'])} finding(s) as inline comments...")
    post_review(args.repo, args.pr, args.sha, diff_text, result)


if __name__ == "__main__":
    main()
