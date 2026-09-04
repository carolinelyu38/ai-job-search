#!/usr/bin/env python3
"""Assemble this workspace into a standalone private repository.

The public fork carries the candidate's profile, contact details and her
employer's client names in its git history, and history survives editing the
files. The fix is a new private repository with a fresh history, not a cleanup
commit on the old one.

    python3 tools/export_private_repo.py --dest /tmp/job-search-private
    python3 tools/export_private_repo.py --dest DIR --dry-run

Two deliberate choices:

* **The repository structure is kept intact.** The 330-test suite asserts the
  framework's own layout: that ci.yml exists, that specific gitignore rules
  behave a certain way, that the README carries the fork warning. Stripping the
  upstream scaffolding breaks thirteen of those tests, so it stays. Actions can
  be switched off in the repository settings if the runner minutes matter.

* **Personal output is force-added.** The fork ignores the generated CVs, cover
  letters, answer sheets and tracker because it is public. A private repository
  exists to keep exactly those, so they are committed past the ignore rules.
  The rules themselves stay, which keeps the next personal file from being
  committed by accident rather than on purpose.

Nothing is deleted from the source checkout. The script only copies.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Never copied: the old history, caches, and per-user Claude Code state.
DROP_PATHS = [".git", ".claude/projects", ".superpowers"]
DROP_NAMES = {"__pycache__", ".venv", "venv", "node_modules"}

# Personal work the public fork ignores. In a private repository these are the
# point, so they are committed explicitly. Missing paths are skipped quietly.
FORCE_ADD = [
    "cv",
    "cover_letters",
    "documents/applications",
    "applicant_answers.json",
    "job_search_tracker.csv",
    "salary_data.json",
    "amazon_watch_seen.json",
    "company_research",
    "reports",
    "upskill",
]

# Files whose only purpose was the public repository's own housekeeping.
SKIP_FORCE = {".gitkeep"}

README_NOTE = """\

---

## This is the private workspace

Assembled from the public fork by `tools/export_private_repo.py`, with a fresh
git history. A public repository is the wrong home for a populated profile:
contact details, and in the experience notes an employer's client names and a
municipal permit number. Editing those files does not help, because git history
keeps every earlier version.

Two things follow, and both matter:

- **Keep this repository private.** The generated CVs, cover letters, answer
  sheets and tracker are committed here on purpose, past the ignore rules that
  hide them in the public fork. Making this repository public would expose the
  profile and every application at once.
- **The public fork is still public.** Deleting it, or switching it to private
  in its GitHub settings, is a separate step that has to be done by hand.

The ignore rules from the fork are kept as they were, so a *new* personal file
is still not committed by accident. Add one deliberately with `git add -f`.

GitHub Actions is inherited from the upstream template. If the runner minutes
matter, turn it off under Settings, Actions, General. The checks run locally:

```
python3 -m unittest discover -s tests
python3 tools/lint_skills.py
python3 tools/security_guards.py
```
"""


def copy_tree(src: Path, dest: Path, dry_run: bool) -> int:
    drop = {src / p for p in DROP_PATHS}
    count = 0
    for path in sorted(src.rglob("*")):
        if any(path == d or d in path.parents for d in drop):
            continue
        if DROP_NAMES & set(path.relative_to(src).parts):
            continue
        target = dest / path.relative_to(src)
        if path.is_dir():
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        count += 1
    return count


def force_add(dest: Path, git) -> list[str]:
    """git add -f the personal output, one existing path at a time."""
    added = []
    for rel in FORCE_ADD:
        p = dest / rel
        if not p.exists():
            continue
        files = [f for f in (p.rglob("*") if p.is_dir() else [p])
                 if f.is_file() and f.name not in SKIP_FORCE]
        if not files:
            continue
        git("add", "-f", "--", *[str(f.relative_to(dest)) for f in files])
        added.append(f"{rel} ({len(files)})")
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="directory to build the repo in")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    dest = Path(args.dest).resolve()
    if dest.exists() and any(dest.iterdir()):
        print(f"refusing to build into a non-empty directory: {dest}", file=sys.stderr)
        return 2
    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    count = copy_tree(REPO, dest, args.dry_run)
    print(f"copied {count} files into {dest}")
    if args.dry_run:
        return 0

    readme = dest / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + README_NOTE, encoding="utf-8")

    if args.no_commit:
        return 0

    def git(*a):
        return subprocess.run(["git", "-C", str(dest), *a], check=True,
                              capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    added = force_add(dest, git)
    git("commit", "-q", "-m",
        "Initial commit: private job search workspace\n\n"
        "Fresh history, assembled by tools/export_private_repo.py. The "
        "generated applications, answer sheets and tracker are committed past "
        "the public fork's ignore rules, which is what this repository is for.")

    tracked = git("ls-files").stdout.count("\n")
    print(f"initial commit on branch main, {tracked} files tracked")
    for line in added:
        print(f"  force-added {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
