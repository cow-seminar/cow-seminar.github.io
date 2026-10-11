#!/usr/bin/env python3
"""Point the slide links on researchseminars.org to the PDFs on https://cow-seminar.github.io.

Every talk of the series CombinatoricsOnWords on researchseminars.org whose slide link is
empty or points to the old wiki (i2m.univ-amu.fr) gets the link to the same talk's slides
on the new site. Talks are matched by date (Paris time) and the speaker's name.

Usage (Python 3.9+, nothing to install):

    python3 update_researchseminars.py            # dry run: only shows what would change
    python3 update_researchseminars.py --apply    # really changes the links

Authentication: researchseminars.org account e-mail and API token (on https://researchseminars.org/user/info;
editing through the API has to be enabled once by writing to the site team). Give them as
environment variables RS_EMAIL and RS_TOKEN, or type them when asked.
"""
import argparse
import datetime as dt
import getpass
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

SERIES = "CombinatoricsOnWords"
SITE_INDEX = "https://cow-seminar.github.io/talks.json"
API = "https://researchseminars.org/api/0"
OLD = "i2m.univ-amu.fr"
PARIS = ZoneInfo("Europe/Paris")


def ascii_letters(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z]", "", s.encode("ascii", "ignore").decode().lower())


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "cow-seminar-sync", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post_json(url, payload, auth):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "authorization": auth,
                                          "User-Agent": "cow-seminar-sync"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"error": str(e)}


def paris_date(start_time):
    """'2020-06-29 09:00:00-04:00' -> '2020-06-29' in Paris time."""
    t = dt.datetime.fromisoformat(start_time.strip().replace(" ", "T"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(PARIS).strftime("%Y-%m-%d")


def match(rs_talk, site_by_date):
    cands = [t for t in site_by_date.get(paris_date(rs_talk["start_time"]), []) if t["slides"]]
    if len(cands) <= 1:
        return cands[0] if cands else None
    name = ascii_letters(rs_talk.get("speaker"))
    named = [t for t in cands if any(w in name for w in t["surnames"] if len(w) >= 3)]
    return named[0] if len(named) == 1 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really change the links (default: dry run)")
    ap.add_argument("--all", action="store_true",
                    help="also replace slide links that point somewhere other than the old wiki")
    args = ap.parse_args()

    auth = None
    if args.apply:
        email = os.environ.get("RS_EMAIL") or input("researchseminars.org e-mail: ").strip()
        token = os.environ.get("RS_TOKEN") or getpass.getpass("API token: ").strip()
        auth = f"{email} {token}"

    site = get_json(SITE_INDEX)
    by_date = {}
    for t in site:
        by_date.setdefault(t["date"], []).append(t)

    q = urllib.parse.urlencode({"series_id": json.dumps(SERIES)})
    rs = get_json(f"{API}/lookup/series?{q}", {"authorization": auth} if auth else None)
    talks = rs.get("talks") or rs.get("properties", {}).get("talks") or []
    talks = [t for t in talks if not t.get("deleted")]
    print(f"researchseminars.org: {len(talks)} talks; new site: {len(site)} talks\n")

    plan, no_new, skipped = [], [], 0
    for t in talks:
        cur = (t.get("slides_link") or "").strip()
        if cur and OLD not in cur and not args.all:
            skipped += 1
            continue
        m = match(t, by_date)
        if not m:
            if cur:  # an old wiki link we cannot replace
                no_new.append(t)
            continue
        new = m["slides"][0]
        if new != cur:
            plan.append((t, cur, new))

    for t, cur, new in plan:
        print(f"#{t['seminar_ctr']:>3}  {paris_date(t['start_time'])}  {t['speaker']}")
        print(f"      {cur or '(no link)'}\n   -> {new}")
    print(f"\n{len(plan)} links to change; {skipped} talks already link elsewhere (left as is).")
    if no_new:
        print("Old wiki links with no slides on the new site (left as is):")
        for t in no_new:
            print(f"   #{t['seminar_ctr']}  {paris_date(t['start_time'])}  {t['speaker']}")

    if not args.apply:
        print("\nDry run only. Run again with --apply to make these changes.")
        return

    ok = 0
    for t, cur, new in plan:
        status, resp = post_json(f"{API}/save/talk/", {"series_id": SERIES, "series_ctr": t["seminar_ctr"],
                                                       "slides_link": new}, auth)
        if status == 200 and resp.get("code") in ("success", "warning"):
            ok += 1
        else:
            print(f"FAILED #{t['seminar_ctr']} {t['speaker']}: {status} {resp}")
            if status == 401:
                sys.exit("Authorization failed: check the e-mail and API token (and that API editing is enabled).")
    print(f"\nDone: {ok} of {len(plan)} links changed.")


if __name__ == "__main__":
    main()
