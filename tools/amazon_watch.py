#!/usr/bin/env python3
"""Watch amazon.jobs for Canadian roles that fit an early-career operations profile.

Amazon's Canadian non-technical hiring is dominated by Area Manager II and Site
Procurement Manager, both of which require two or more years of people
management. The roles worth catching are rarer: the Early Career and Pathways
pipelines, and the occasional junior seat in Program Management (Non-Tech),
supply chain, procurement or planning.

    python3 tools/amazon_watch.py              # report anything new since last run
    python3 tools/amazon_watch.py --all        # ignore the seen list, show everything matching
    python3 tools/amazon_watch.py --days 7     # only postings this recent (default 7)

Exit code is 0 when something worth reading turned up and 1 when nothing did,
so the scheduled Routine can stay silent on a quiet morning.

State lives in data/amazon_watch_state.json and is committed on purpose. The
scheduled Routine that runs this script gets a fresh container each morning, so
an ignored state file would reset daily and the evergreen Early Career postings
would be re-reported forever.

Note on the API: amazon.jobs ignores country[] on its own. Only
normalized_state_name[] filters reliably, so the search runs province by
province.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PROVINCES = [
    "British Columbia", "Ontario", "Quebec", "Alberta", "Manitoba",
    "Saskatchewan", "Nova Scotia", "New Brunswick",
    "Newfoundland and Labrador", "Prince Edward Island",
]

# Categories worth reading at all.
CATEGORIES = {
    "Project/Program/Product Management--Non-Tech",
    "Fulfillment & Operations Management",
    "Buying, Planning, & Instock Management",
    "Procurement",
    "Business Intelligence",
    "Business & Merchant Development",
    "Supply Chain/Transportation Management",
}

# Titles worth reading regardless of category.
TITLE_KEEP = re.compile(
    r"early career|new grad|pathways|university|graduate program|rotational|"
    r"program manager|program coordinator|supply chain|logistic|procure|sourcing|"
    r"inventory|planner|instock|transportation|vendor|trade compliance|"
    r"business analyst|process improvement|operations analyst",
    re.I,
)

# Hard exclusions on the title alone.
TITLE_DROP = re.compile(
    r"\b(senior|sr\.?|principal|staff|head of|director|vp|chief|"
    r"engineer|engineering|developer|scientist|sde|software|technician|"
    r"mechatronic|architect|iii|iv)\b",
    re.I,
)

# Hourly floor roles and French-language postings. She is not looking for shift
# warehouse work, and her French is conversational and untested.
TITLE_DROP_ALSO = re.compile(
    r"warehouse associate|inventory and warehouse|fulfillment associate|"
    r"delivery station|sortation|picker|packer|associ\u00e9|associe |"
    r"gestionnaire|sp\u00e9cialiste|conseiller|responsable|analyste|"
    r"technicien|coordonnateur|op\u00e9rations",
    re.I,
)

# Signals in the body that the role is reachable at 0-2 years.
JUNIOR_SIGNAL = re.compile(
    r"in the process of obtaining a bachelor|currently enrolled|"
    r"recent graduate|early career|no prior experience|"
    r"(?<!\d)(?:0|1|one)\+?\s*(?:to\s*\d+\s*)?years?", re.I,
)
YEARS = re.compile(r"(\d+)\+?\s*years?", re.I)
PEOPLE_MGMT = re.compile(
    r"\d+\+?\s*years? of (employee and performance management|people management|"
    r"management experience|leading|supervising)", re.I)


def fetch(url: str, timeout: int = 50) -> str:
    r = subprocess.run(["curl", "-sL", "-A", UA, url, "--max-time", str(timeout)],
                       capture_output=True, text=True)
    return r.stdout


def search_province(province: str) -> list[dict]:
    jobs, seen_paths = [], set()
    for offset in range(0, 400, 100):
        url = ("https://www.amazon.jobs/en/search.json?country%5B%5D=CAN"
               f"&normalized_state_name%5B%5D={urllib.parse.quote_plus(province)}"
               f"&sort=recent&result_limit=100&offset={offset}")
        try:
            batch = (json.loads(fetch(url)).get("jobs") or [])
        except Exception:
            break
        for j in batch:
            p = j.get("job_path")
            if p and p not in seen_paths:
                seen_paths.add(p)
                jobs.append(j)
        if len(batch) < 100:
            break
        time.sleep(0.3)
    return jobs


def posted(job: dict):
    s = (job.get("posted_date") or "").replace("  ", " ").strip()
    for fmt in ("%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def body_text(job: dict) -> str:
    html_src = fetch("https://www.amazon.jobs" + (job.get("job_path") or ""), 45)
    s = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", html_src)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|ul|h[1-6])>", "\n", s)
    import html as _html
    t = _html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\xa0]+", " ", t)


def assess(job: dict) -> tuple[str, str]:
    """Return (verdict, reason) after reading the posting body."""
    t = body_text(job)
    upper = t.upper()
    i = upper.find("BASIC QUALIFICATIONS")
    quals = t[i:i + 1600] if i >= 0 else t[:1600]
    # Preferred Qualifications routinely state a lower bar than Basic. Only the
    # Basic section decides whether the role is reachable.
    cut = quals.upper().find("PREFERRED QUALIFICATIONS")
    if cut > 0:
        quals = quals[:cut]
    quals = re.sub(r"\s+", " ", quals)

    if PEOPLE_MGMT.search(quals):
        return "REJECT", "requires prior people-management experience"
    if re.search(r"MBA|master's degree required", quals, re.I):
        return "REJECT", "requires a graduate degree"

    yrs = [int(y) for y in YEARS.findall(quals) if int(y) < 21]
    if JUNIOR_SIGNAL.search(quals) and (not yrs or min(yrs) <= 2):
        return "FIT", "early-career wording, no bar above 2 years"
    if not yrs:
        return "FIT", "no years-of-experience requirement stated"
    if min(yrs) <= 2:
        return "FIT", f"lowest stated bar is {min(yrs)} year(s)"
    if min(yrs) <= 3:
        return "STRETCH", f"lowest stated bar is {min(yrs)} years"
    return "REJECT", f"requires {min(yrs)}+ years"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true", help="ignore the seen list")
    ap.add_argument("--state", default="data/amazon_watch_state.json")
    args = ap.parse_args()

    seen = set()
    if os.path.exists(args.state) and not args.all:
        seen = set(json.load(open(args.state)).get("seen", []))

    today = datetime.date.today()
    by_path: dict[str, dict] = {}
    for province in PROVINCES:
        for j in search_province(province):
            by_path.setdefault(j.get("job_path"), j)
        time.sleep(0.2)
    everything = list(by_path.values())

    shortlist = []
    for j in everything:
        title = j.get("title", "")
        if TITLE_DROP.search(title) or TITLE_DROP_ALSO.search(title):
            continue
        if not (j.get("job_category") in CATEGORIES or TITLE_KEEP.search(title)):
            continue
        evergreen = bool(re.search(
            r"early career|new grad|pathways|university|graduate program|intern",
            title, re.I))
        d = posted(j)
        if d and not evergreen and (today - d).days > args.days:
            continue
        if j.get("job_path") in seen:
            continue
        shortlist.append(j)

    print(f"Amazon Canada: {len(everything)} live postings, "
          f"{len(shortlist)} new and in scope (last {args.days} days)\n")

    fits, stretches = [], []
    for j in shortlist:
        verdict, reason = assess(j)
        line = (f'{str(posted(j)):10} | {j.get("title","")[:58]:58} | '
                f'{(j.get("normalized_location") or "")[:22]:22} | {reason}')
        if verdict == "FIT":
            fits.append((line, j))
        elif verdict == "STRETCH":
            stretches.append((line, j))
        time.sleep(0.25)

    if fits:
        print("WORTH APPLYING")
        for line, j in fits:
            print("  " + line)
            print("     https://www.amazon.jobs" + (j.get("job_path") or ""))
    if stretches:
        print("\nSTRETCH (3 years stated)")
        for line, j in stretches:
            print("  " + line)
            print("     https://www.amazon.jobs" + (j.get("job_path") or ""))
    if not fits and not stretches:
        print("Nothing new that clears the level bar.")

    seen |= {j.get("job_path") for j in shortlist if j.get("job_path")}
    os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
    json.dump({"seen": sorted(p for p in seen if p),
               "last_run": today.isoformat()}, open(args.state, "w"), indent=1)
    return 0 if (fits or stretches) else 1


if __name__ == "__main__":
    sys.exit(main())
