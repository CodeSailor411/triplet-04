"""Validate PR file boundaries using the policy from the base commit, not the PR."""

import argparse
import json
import subprocess


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def validate(branch: str, base_branch: str, paths: list[str], policy: dict) -> list[str]:
    rules = policy["branches"].get(branch)
    if rules is None:
        return [f"Unknown CIVIS work branch: {branch}"]
    expected_base = "brain" if branch == policy["integration_branch"] else policy["integration_branch"]
    errors = []
    if base_branch != expected_base:
        errors.append(f"Wrong PR base: use {expected_base}, not {base_branch}")
    for path in paths:
        if not any(path.startswith(rule) if rule.endswith("/") else path == rule for rule in rules):
            errors.append(f"Outside {branch}'s assigned files: {path}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    parser.add_argument("--base-branch", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    raw = git("show", f"{args.base_sha}:brain/scripts/ownership.json")
    policy = json.loads(raw)
    # --no-renames also checks both paths when a protected file is moved.
    paths = [p for p in git("diff", "--no-renames", "--name-only", "-z",
                           f"{args.base_sha}...{args.head_sha}").split("\0") if p]
    errors = validate(args.branch, args.base_branch, paths, policy)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"File ownership passed for {len(paths)} changed files.")
