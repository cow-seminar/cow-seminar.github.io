#!/usr/bin/env python3
"""Builds the seminar website into _site/ from talks.yml, about.md, config.yml and slides/.

Run locally:  pip install pyyaml markdown  &&  python build.py
GitHub runs this automatically (see .github/workflows/build.yml).
"""
import datetime as dt
import html
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import yaml

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
SLIDES_DIR = ROOT / "slides"

warnings = []


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------- loading

def load_config():
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8")) or {}
    cfg.setdefault("title", "Seminar")
    cfg.setdefault("timezone", "Europe/Paris")
    cfg.setdefault("default_time", "15:00")
    cfg.setdefault("talk_duration_minutes", 60)
    cfg.setdefault("site_url", "")
    return cfg


def ascii_letters(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z]", "", s.encode("ascii", "ignore").decode().lower())


def index_slides():
    """Map 'YYYYMMDD' -> list of slide paths (relative to repo root), plus basename index."""
    by_date, by_name = {}, {}
    if SLIDES_DIR.exists():
        for p in sorted(SLIDES_DIR.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            rel = p.relative_to(ROOT).as_posix()
            by_name.setdefault(p.name, []).append(rel)
            m = re.match(r"(\d{8})", p.name)
            if m:
                by_date.setdefault(m.group(1), []).append(rel)
    return by_date, by_name


def parse_time(value, default):
    s = str(value if value not in (None, "") else default).strip()
    m = re.fullmatch(r"(\d{1,2})[:h.](\d{2})", s)
    if not m:
        raise ValueError(f"cannot read time '{s}'")
    return dt.time(int(m.group(1)), int(m.group(2)))


def load_talks(cfg, tz):
    raw = yaml.safe_load((ROOT / "talks.yml").read_text(encoding="utf-8")) or []
    by_date, by_name = index_slides()
    used = set()
    talks = []
    for i, t in enumerate(raw, 1):
        if not isinstance(t, dict) or "date" not in t:
            warn(f"talks.yml: entry #{i} has no date, skipped")
            continue
        d = t["date"]
        if isinstance(d, str):
            d = dt.date.fromisoformat(d.strip())
        elif isinstance(d, dt.datetime):
            d = d.date()
        start = dt.datetime.combine(d, parse_time(t.get("time"), cfg["default_time"]), tzinfo=tz)
        talk = dict(t)
        talk["date"] = d
        talk["start"] = start

        # --- slides: explicit value, or automatic lookup by date prefix YYYYMMDD
        slides = []
        explicit = t.get("slides")
        if explicit:
            for item in explicit if isinstance(explicit, list) else [explicit]:
                item = str(item).strip()
                if re.match(r"https?://", item):
                    slides.append(item)
                elif (ROOT / item).is_file():
                    slides.append(item)
                elif (SLIDES_DIR / item).is_file():
                    slides.append(f"slides/{item}")
                elif item in by_name:
                    slides.extend(by_name[item])
                else:
                    warn(f"{d} {t.get('speaker')}: slides file '{item}' not found")
        else:
            cands = by_date.get(d.strftime("%Y%m%d"), [])
            if len(cands) > 1:  # several files that day: prefer those mentioning the surname
                surname = ascii_letters((t.get("speaker") or "").split()[-1] if t.get("speaker") else "")
                named = [c for c in cands if surname and surname in ascii_letters(Path(c).name)]
                cands = named or cands
            slides = cands
        used.update(s for s in slides if not s.startswith("http"))
        talk["slides_list"] = slides
        talks.append(talk)

    all_files = {p for lst in by_name.values() for p in lst}
    for f in sorted(all_files - used):
        warn(f"slides file not attached to any talk: {f}")
    talks.sort(key=lambda x: x["start"])
    return talks


# ---------------------------------------------------------------- rendering

URL_RE = re.compile(r"(https?://[^\s<>\"]+[^\s<>\".,;:!?)])")


def text_to_html(text):
    """Plain text with blank-line paragraphs; $...$ math is left for MathJax."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", str(text or "").strip()) if p.strip()]
    out = []
    for p in paras:
        p = html.escape(p, quote=False)
        p = URL_RE.sub(r'<a href="\1">\1</a>', p)
        out.append(f"<p>{p}</p>")
    return "\n".join(out)


def esc(s):
    return html.escape(str(s or ""))


def talk_html(t, cfg, collapse_abstract, prefix):
    start = t["start"]
    when = start.strftime("%A, %B ") + str(start.day) + start.strftime(", %Y")
    when += f" · {start.strftime('%H:%M')} {cfg['timezone'].split('/')[-1].replace('_', ' ')} time"
    speaker = esc(t.get("speaker"))
    if t.get("speaker_url"):
        speaker = f'<a href="{esc(t["speaker_url"])}">{speaker}</a>'
    title = f'<p class="talk-title">{esc(t["title"])}</p>' if t.get("title") else \
        '<p class="talk-title tba">Title to be announced</p>'

    links = []
    sl = t["slides_list"]
    for k, s in enumerate(sl, 1):
        href = s if s.startswith("http") else prefix + s
        label = "Slides" if len(sl) == 1 else f"Slides ({k})"
        links.append(f'<a class="pill" href="{esc(href)}">{label}</a>')
    if t.get("video"):
        links.append(f'<a class="pill" href="{esc(t["video"])}">Video</a>')
    if t.get("note"):
        links.append(f'<span class="note">{esc(t["note"])}</span>')
    links_html = f'<div class="talk-links">{"".join(links)}</div>' if links else ""

    abstract = ""
    if t.get("abstract"):
        body = text_to_html(t["abstract"])
        abstract = (f'<details class="abstract"><summary>Abstract</summary>{body}</details>'
                    if collapse_abstract else f'<div class="abstract">{body}</div>')

    anchor = start.strftime("%Y%m%d") + "-" + ascii_letters((t.get("speaker") or "x").split()[-1])
    return f"""<article class="talk" id="{anchor}">
  <div class="talk-date"><a href="#{anchor}">{when}</a></div>
  <h3 class="speaker">{speaker}</h3>
  {title}
  {links_html}
  {abstract}
</article>"""


def page(cfg, title, body, prefix=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{prefix}style.css">
<link rel="alternate" type="text/calendar" href="{prefix}calendar.ics" title="Seminar calendar">
<script>
window.MathJax = {{ tex: {{ inlineMath: [['$','$'], ['\\\\(','\\\\)']], processEscapes: true }} }};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
</head>
<body>
<main>
{body}
<footer>Page updated {dt.datetime.now(ZoneInfo(cfg['timezone'])).strftime('%Y-%m-%d %H:%M')} ({esc(cfg['timezone'])}).</footer>
</main>
</body>
</html>
"""


def ics_escape(s):
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def build_ics(cfg, talks):
    fmt = "%Y%m%dT%H%M%SZ"
    now = dt.datetime.now(dt.timezone.utc).strftime(fmt)
    host = re.sub(r"^https?://", "", cfg["site_url"]).strip("/") or "seminar"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{host}//seminar//EN",
             f"X-WR-CALNAME:{ics_escape(cfg['title'])}", "CALSCALE:GREGORIAN"]
    for t in talks:
        s = t["start"].astimezone(dt.timezone.utc)
        e = s + dt.timedelta(minutes=int(cfg["talk_duration_minutes"]))
        summary = f"{t.get('speaker', '')}: {t['title']}" if t.get("title") else t.get("speaker", "")
        lines += ["BEGIN:VEVENT",
                  f"UID:{s.strftime('%Y%m%d')}-{ascii_letters(t.get('speaker'))}@{host}",
                  f"DTSTAMP:{now}", f"DTSTART:{s.strftime(fmt)}", f"DTEND:{e.strftime(fmt)}",
                  f"SUMMARY:{ics_escape(summary)}",
                  f"DESCRIPTION:{ics_escape((t.get('abstract') or '').strip())}",
                  f"URL:{cfg['site_url'].rstrip('/')}/#{s.strftime('%Y%m%d')}-{ascii_letters((t.get('speaker') or 'x').split()[-1])}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------- main

def main():
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz)
    talks = load_talks(cfg, tz)

    upcoming = [t for t in talks if t["start"] > now]
    past = sorted((t for t in talks if t["start"] <= now), key=lambda t: t["start"], reverse=True)
    this_year = [t for t in past if t["start"].year == now.year]
    archive_years = sorted({t["start"].year for t in past if t["start"].year < now.year}, reverse=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "archives").mkdir()

    about = markdown.markdown((ROOT / "about.md").read_text(encoding="utf-8"))

    nav = ['<a href="#upcoming">Upcoming talks</a>']
    if this_year:
        nav.append(f'<a href="#past">Past talks {now.year}</a>')
    nav += [f'<a href="archives/{y}.html">{y}</a>' for y in archive_years]

    parts = [f"<header><h1>{esc(cfg['title'])}</h1><nav>{' · '.join(nav)}</nav></header>",
             f'<section class="about">{about}</section>',
             '<section id="upcoming"><h2>Upcoming talks</h2>']
    parts += [talk_html(t, cfg, False, "") for t in upcoming] or ['<p class="empty">No talks announced yet.</p>']
    parts.append("</section>")
    if this_year:
        parts.append(f'<section id="past"><h2>Past talks {now.year}</h2>')
        parts += [talk_html(t, cfg, True, "") for t in this_year]
        parts.append("</section>")
    if archive_years:
        parts.append('<section id="archives"><h2>Archives</h2><ul class="years">')
        parts += [f'<li><a href="archives/{y}.html">Talks of {y}</a></li>' for y in archive_years]
        parts.append("</ul></section>")
    (OUT / "index.html").write_text(page(cfg, cfg["title"], "\n".join(parts)), encoding="utf-8")

    for y in archive_years:
        body = [f'<header><p class="back"><a href="../index.html">← {esc(cfg["title"])}</a></p>'
                f'<h1>Talks of {y}</h1><nav>' +
                " · ".join(f'<a href="{z}.html">{z}</a>' if z != y else f"<strong>{z}</strong>" for z in archive_years) +
                "</nav></header>"]
        body += [talk_html(t, cfg, True, "../") for t in past if t["start"].year == y]
        (OUT / "archives" / f"{y}.html").write_text(
            page(cfg, f"{y} · {cfg['title']}", "\n".join(body), "../"), encoding="utf-8")

    (OUT / "calendar.ics").write_text(build_ics(cfg, talks), encoding="utf-8", newline="")
    shutil.copy(ROOT / "style.css", OUT / "style.css")
    if SLIDES_DIR.exists():
        shutil.copytree(SLIDES_DIR, OUT / "slides")
    (OUT / ".nojekyll").write_text("")

    print(f"Built: {len(upcoming)} upcoming, {len(this_year)} past this year, "
          f"archives: {', '.join(map(str, archive_years)) or 'none'}")
    for w in warnings:
        print("WARNING:", w)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning::{w}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, yaml.YAMLError) as e:
        msg = f"Error in the data files: {e}"
        print(f"::error::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg, file=sys.stderr)
        sys.exit(1)
