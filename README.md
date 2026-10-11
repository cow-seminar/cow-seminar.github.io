# One World Combinatorics on Words Seminar: website

Site: https://cow-seminar.github.io

Everything can be edited directly on github.com; nothing needs to be installed.
After every commit the site rebuilds itself in about 1–2 minutes.

## Which file does what

| File | Contents |
|---|---|
| `talks.yml` | current talks: upcoming and recent |
| `archive/talks-YEAR.yml` | talks of 2020–2025, imported from the old wiki (same format) |
| `about.md` | the header text: schedule, Zoom, organizers |
| `slides/YEAR/` | PDF slides |
| `config.yml` | site title, time zone, default talk time |
| `build.py`, `style.css`, `.github/` | the site engine; no need to touch these |

## Announcing a new talk

1. Open `talks.yml` and click the pencil icon (Edit).
2. Add an entry anywhere (order does not matter; indent with spaces, not tabs):

   ```yaml
   - date: 2027-01-12
     speaker: First Last
     speaker_url: https://...
     title: Title of the talk
     abstract: |
       Abstract text, formulas in $...$.

       An empty line starts a new paragraph.
   ```
3. Click **Commit changes**.

If the title is not known yet, just leave out `title`; the site will show "Title to be announced".
Inside an abstract you can write `*italic*`, `**bold**`, links as `[text](https://...)`,
and lists with lines starting with `- `.
A talk at an unusual time: add `time: "16:00"` (Paris time).

## After the talk

The talk moves from "Upcoming" to "Past talks" **by itself** the same evening.
On January 1 the previous year's talks move to their own archive page automatically
(they can stay in `talks.yml`; which file a talk is in does not matter).

**Slides:** upload the PDF to `slides/2027/` (Add file → Upload files).
If the file name starts with the date of the talk, e.g. `20270112smith.pdf`, the slides
are attached to that day's talk automatically; nothing needs to be added to `talks.yml`.
For a file with a different name, give it explicitly in the talk entry: `slides: some_name.pdf`.

**Video:** add the line `video: https://youtu.be/...` to the talk entry.

**Not recorded:** `note: The talk was not recorded at the speaker's request.`

## If something goes wrong

Open the **Actions** tab. A green check mark means the site is updated; a red cross means an error.
Click the red cross to see which entry caused it. Usually it is a broken indentation or a colon
inside a title; put such a title in quotes: `title: "A: B"`.
The same page shows warnings such as "slides file not attached to any talk": a PDF that
could not be matched to any talk.

**Actions → Build and publish the site → Run workflow** rebuilds the site manually.

Note: GitHub pauses scheduled rebuilds if the repository has had no commits for 60 days
(for instance over the summer). After such a break, any commit or the Run workflow button
turns them back on.

## How the page works

The main page has two tabs, "Upcoming talks" and "Past talks" of the current year; the column on
the right links to the archive page of every earlier year. Each talk is one row (time, speaker,
title); clicking it opens the abstract, slides and video. Times are shown in the reader's own
time zone. A link to a single talk looks like `https://cow-seminar.github.io/#20261013-kosoy`.

## Slide links on researchseminars.org

`tools/update_researchseminars.py` points the slide links of our talks on researchseminars.org
to the PDFs on this site (matching talks by date and speaker). Run it on your own computer:
`python3 update_researchseminars.py` shows what would change, `--apply` changes it.
It needs your researchseminars.org e-mail and API token (see the comment at the top of the script).
Run it again whenever new slides have been added here.
