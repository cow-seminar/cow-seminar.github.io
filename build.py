#!/usr/bin/env python3
"""Builds the seminar website into _site/.

Inputs: config.yml, about.md, talks.yml, archive/*.yml and the PDFs in slides/.
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
    cfg.setdefault("youtube_url", "")
    return cfg


def ascii_letters(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^a-z]", "", s.encode("ascii", "ignore").decode().lower())


def plain(s):
    """Strip markdown links/emphasis: '[Ann](url) and *x*' -> 'Ann and x'."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(s or ""))
    return s.replace("**", "").replace("*", "")


def surname_words(speaker):
    return [ascii_letters(w) for w in re.split(r"[\s,]+", plain(speaker))
            if len(ascii_letters(w)) >= 3 and w.lower() not in ("and", "with")]


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


def read_entries():
    files = [ROOT / "talks.yml"] + sorted((ROOT / "archive").glob("*.yml"))
    for f in files:
        if not f.exists():
            continue
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as e:
            raise ValueError(f"{f.relative_to(ROOT)}: {e}")
        for i, t in enumerate(data, 1):
            yield f.relative_to(ROOT).as_posix(), i, t


def load_talks(cfg, tz):
    by_date, by_name = index_slides()
    day_count = {}
    raw = list(read_entries())
    for _, _, t in raw:
        if isinstance(t, dict) and "date" in t:
            day_count[str(t["date"])] = day_count.get(str(t["date"]), 0) + 1
    used = set()
    talks = []
    for fname, i, t in raw:
        if not isinstance(t, dict) or "date" not in t:
            warn(f"{fname}: entry #{i} has no date, skipped")
            continue
        d = t["date"]
        try:
            if isinstance(d, str):
                d = dt.date.fromisoformat(d.strip())
            elif isinstance(d, dt.datetime):
                d = d.date()
            start = dt.datetime.combine(d, parse_time(t.get("time"), cfg["default_time"]), tzinfo=tz)
        except ValueError as e:
            raise ValueError(f"{fname}, entry #{i} ({t.get('speaker')}): {e}")
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
                    warn(f"{d} {plain(t.get('speaker'))}: slides file '{item}' not found")
        else:
            cands = by_date.get(d.strftime("%Y%m%d"), [])
            if day_count.get(str(t["date"]), 0) > 1 or len(cands) > 1:
                # several talks or files that day: match by the speaker's name
                words = surname_words(t.get("speaker"))
                cands = [c for c in cands if any(w in ascii_letters(Path(c).name) for w in words)]
            slides = cands
        used.update(s for s in slides if not s.startswith("http"))
        talk["slides_list"] = slides
        talks.append(talk)

    all_files = {p for lst in by_name.values() for p in lst}
    for f in sorted(all_files - used):
        warn(f"slides file not attached to any talk: {f}")
    talks.sort(key=lambda x: x["start"])
    return talks


# ---------------------------------------------------------------- text rendering

URL_RE = re.compile(r"(?<![\"(=])(https?://[^\s<>\"]+[^\s<>\".,;:!?)\]])")
MATH_RE = re.compile(r"(\$\$.+?\$\$|\\\[.+?\\\]|\$[^$]+\$)", re.S)


def inline(text):
    """Escape HTML; render [label](url), **bold**, *italic* and bare URLs, leaving math untouched."""
    maths, links = [], []

    def keep_math(m):
        maths.append(html.escape(m.group(0), quote=False))
        return f"\x01{len(maths) - 1}\x01"
    p = MATH_RE.sub(keep_math, str(text or ""))
    p = html.escape(p, quote=False)

    def keep_link(m):
        links.append(f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>')
        return f"\x00{len(links) - 1}\x00"
    p = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", keep_link, p)
    p = URL_RE.sub(r'<a href="\1">\1</a>', p)
    p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p, flags=re.S)
    p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", p, flags=re.S)
    p = re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], p)
    p = re.sub(r"\x01(\d+)\x01", lambda m: maths[int(m.group(1))], p)
    return p


def text_to_html(text):
    """Blank line = new paragraph; lines starting with '- ' become list items."""
    blocks = []  # ("p", [lines]) or ("ul", [items])
    bullet = re.compile(r"^[-*•]\s+")
    for para in re.split(r"\n\s*\n", str(text or "").strip()):
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        cur = None
        for l in lines:
            if bullet.match(l):
                if not blocks or blocks[-1][0] != "ul" or cur == "p":
                    blocks.append(("ul", []))
                blocks[-1][1].append(bullet.sub("", l))
                cur = "ul"
            elif cur == "ul":
                blocks[-1][1][-1] += " " + l       # continuation of a list item
            else:
                if cur != "p":
                    blocks.append(("p", []))
                blocks[-1][1].append(l)
                cur = "p"
    out = []
    for kind, items in blocks:
        if kind == "ul":
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
        else:
            out.append("<p>" + inline(" ".join(items)) + "</p>")
    return "\n".join(out)


def esc(s):
    return html.escape(str(s or ""))


# ---------------------------------------------------------------- page pieces

def anchor_of(t):
    words = surname_words(t.get("speaker")) or ["talk"]
    return t["start"].strftime("%Y%m%d") + "-" + words[-1]


def talk_html(t, cfg, prefix, open_=False, show_year=False):
    start = t["start"]
    utc = start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fmt = "%a %b %-d" + (" %Y" if show_year else "") + ", %H:%M"
    fallback = start.strftime(fmt)

    if t.get("speaker_url"):
        speaker_full = f'<a href="{esc(t["speaker_url"])}">{esc(plain(t.get("speaker")))}: web page</a>'
    elif "](" in str(t.get("speaker")):
        speaker_full = inline(t.get("speaker"))
    else:
        speaker_full = ""
    speaker_short = esc(plain(t.get("speaker")))
    title = inline(t["title"]) if t.get("title") else '<span class="tba">Title to be announced</span>'

    links, badges = [], []
    sl = t["slides_list"]
    for k, s in enumerate(sl, 1):
        href = s if s.startswith("http") else prefix + s
        label = "Slides" if len(sl) == 1 else f"Slides {k}"
        links.append(f'<a class="btn" href="{esc(href)}">{label} <small>PDF</small></a>')
    badges.append('<span class="badge" title="Slides available">PDF</span>' if sl else '<span></span>')
    if t.get("video"):
        links.append(f'<a class="btn" href="{esc(t["video"])}">Video <small>YouTube</small></a>')
        badges.append('<span class="badge" title="Video available">▶</span>')
    else:
        badges.append('<span></span>')
    note = f'<p class="note">{inline(t["note"])}</p>' if t.get("note") else ""
    links_html = f'<div class="links">{"".join(links)}</div>' if links else ""
    abstract = f'<div class="abstract">{text_to_html(t["abstract"])}</div>' if t.get("abstract") else ""

    return f"""<details class="talk" id="{anchor_of(t)}"{' open' if open_ else ''}>
<summary>
  <time class="when" datetime="{utc}" data-year="{1 if show_year else 0}">{fallback}</time>
  <span class="who">{speaker_short}</span>
  <span class="what">{title}</span>
  <span class="badges">{''.join(badges)}</span>
</summary>
<div class="detail">
  {f'<p class="speaker-line">{speaker_full}</p>' if speaker_full else ''}
  {links_html}{note}{abstract}
</div>
</details>"""


def talk_list(talks, cfg, prefix, open_=False, show_year=False, empty="No talks."):
    if not talks:
        return f'<p class="empty">{empty}</p>'
    rows = "\n".join(talk_html(t, cfg, prefix, open_ and k == 0, show_year) for k, t in enumerate(talks))
    return f"""<div class="list">
<div class="list-head"><span>Your time</span><span>Speaker</span><span>Title</span><span></span></div>
{rows}
</div>"""


def sidebar(cfg, years, prefix, current=None):
    items = []
    for y in years:
        cls = ' class="current"' if y == current else ""
        items.append(f'<li><a{cls} href="{prefix}archives/{y}.html">{y}</a></li>')
    yt = (f'<li><a href="{esc(cfg["youtube_url"])}">YouTube channel</a></li>' if cfg.get("youtube_url") else "")
    return f"""<aside class="side">
  <nav class="box">
    <h2>Seminar</h2>
    <ul><li><a{' class="current"' if current is None else ''} href="{prefix}index.html">Current talks</a></li>{yt}
    <li><a href="{prefix}calendar.ics">Calendar (.ics)</a></li></ul>
  </nav>
  <nav class="box">
    <h2>Archives</h2>
    <ul class="years">{''.join(items) or '<li class="empty">—</li>'}</ul>
  </nav>
</aside>"""


SCRIPT = r"""
<script>
(function () {
  // Times in the reader's own time zone
  var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  document.querySelectorAll('time.when').forEach(function (el) {
    var d = new Date(el.getAttribute('datetime'));
    var opts = {weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false};
    if (el.dataset.year === '1') opts.year = 'numeric';
    el.textContent = d.toLocaleString('en-GB', opts).replace(/,(?=[^,]*$)/, ',');
    el.title = 'Paris: ' + d.toLocaleString('en-GB', Object.assign({}, opts, {timeZone: 'Europe/Paris', timeZoneName: 'short'}));
  });
  document.querySelectorAll('.tz-name').forEach(function (el) { el.textContent = tz.replace(/_/g, ' '); });
  document.querySelectorAll('.tz-note').forEach(function (el) { el.hidden = false; });

  // Tabs
  var tabs = document.querySelectorAll('[role=tab]');
  function show(id) {
    tabs.forEach(function (t) {
      var on = t.getAttribute('aria-controls') === id;
      t.setAttribute('aria-selected', on);
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    });
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      show(t.getAttribute('aria-controls'));
      history.replaceState(null, '', t.getAttribute('aria-controls') === 'past' ? '#past' : location.pathname);
    });
  });
  // Open a talk given in the URL (#20261013-kosoy) and show its tab
  var h = location.hash.slice(1), target = h && document.getElementById(h);
  if (tabs.length) show(h === 'past' || (target && target.closest('#past')) ? 'past' : 'upcoming');
  if (target && target.tagName === 'DETAILS') { target.open = true; target.scrollIntoView(); }
})();
</script>"""


def page(cfg, title, main_html, side_html, prefix=""):
    now = dt.datetime.now(ZoneInfo(cfg["timezone"]))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}style.css">
<link rel="alternate" type="text/calendar" href="{prefix}calendar.ics" title="Seminar calendar">
<script>
window.MathJax = {{ tex: {{ inlineMath: [['$','$'], ['\\\\(','\\\\)']], processEscapes: true }},
  options: {{ ignoreHtmlClass: 'no-math' }} }};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
</head>
<body>
<div class="wrap">
<main class="main">
{main_html}
</main>
{side_html}
</div>
<footer class="foot">Updated {now.strftime('%Y-%m-%d %H:%M')} Paris time.</footer>
{SCRIPT}
</body>
</html>
"""


TZ_NOTE = ('<p class="tz-note" hidden>Times are shown in your time zone '
           '(<span class="tz-name"></span>). Hover over a time to see it in Paris time.</p>')


# ---------------------------------------------------------------- calendar

def ics_escape(s):
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    if len(line.encode("utf-8")) <= 75:
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
        sp = plain(t.get("speaker"))
        summary = f"{sp}: {plain(t['title'])}" if t.get("title") else sp
        url = f"{cfg['site_url'].rstrip('/')}/"
        if t["start"].year < dt.datetime.now().year:
            url += f"archives/{t['start'].year}.html"
        url += f"#{anchor_of(t)}"
        lines += ["BEGIN:VEVENT", f"UID:{anchor_of(t)}@{host}", f"DTSTAMP:{now}",
                  f"DTSTART:{s.strftime(fmt)}", f"DTEND:{e.strftime(fmt)}",
                  f"SUMMARY:{ics_escape(summary)}",
                  f"DESCRIPTION:{ics_escape((t.get('abstract') or '').strip())}",
                  f"URL:{url}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------- main

def main():
    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz)
    talks = load_talks(cfg, tz)

    upcoming = [t for t in talks if t["start"] > now]
    # newest day first, but talks of the same day in their actual order
    past = sorted((t for t in talks if t["start"] <= now), key=lambda t: (-t["start"].toordinal(), t["start"]))
    this_year = [t for t in past if t["start"].year == now.year]
    years = sorted({t["start"].year for t in past if t["start"].year < now.year}, reverse=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "archives").mkdir()

    about = markdown.markdown((ROOT / "about.md").read_text(encoding="utf-8"))

    main_html = f"""<header class="masthead"><h1>{esc(cfg['title'])}</h1></header>
<section class="about">{about}</section>
<div class="tabs" role="tablist">
  <button role="tab" aria-selected="true" aria-controls="upcoming">Upcoming talks</button>
  <button role="tab" aria-selected="false" aria-controls="past">Past talks {now.year}</button>
</div>
{TZ_NOTE}
<section id="upcoming" role="tabpanel"><h2 class="panel-title">Upcoming talks</h2>
{talk_list(upcoming, cfg, "", open_=True, empty="No talks announced yet.")}
</section>
<section id="past" role="tabpanel"><h2 class="panel-title">Past talks {now.year}</h2>
{talk_list(this_year, cfg, "", empty="No talks yet this year.")}
</section>"""
    (OUT / "index.html").write_text(page(cfg, cfg["title"], main_html, sidebar(cfg, years, "")), encoding="utf-8")

    for y in years:
        yt = [t for t in past if t["start"].year == y]
        main_html = f"""<header class="masthead"><p class="kicker"><a href="../index.html">{esc(cfg['title'])}</a></p>
<h1>Talks of {y}</h1><p class="count">{len(yt)} talks</p></header>
{TZ_NOTE}
{talk_list(yt, cfg, "../", show_year=False)}"""
        (OUT / "archives" / f"{y}.html").write_text(
            page(cfg, f"{y} · {cfg['title']}", main_html, sidebar(cfg, years, "../", y), "../"),
            encoding="utf-8")

    (OUT / "calendar.ics").write_text(build_ics(cfg, talks), encoding="utf-8", newline="")
    shutil.copy(ROOT / "style.css", OUT / "style.css")
    if SLIDES_DIR.exists():
        shutil.copytree(SLIDES_DIR, OUT / "slides")
    (OUT / ".nojekyll").write_text("")

    print(f"Built: {len(upcoming)} upcoming, {len(this_year)} past this year, "
          f"archives: {', '.join(map(str, years)) or 'none'}")
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
