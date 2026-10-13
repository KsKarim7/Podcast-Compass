# Podcast Compass

Podcast Compass turns a podcast transcript into something you can study from: a summary
with the main themes, a set of key takeaways, navigable chapters, and a short quiz with
answers. The thing it tries to do better than a plain summariser is let you check it —
every takeaway, chapter and quiz answer cites the part of the transcript it came from, and
quotes a few words from it, and the app verifies that quote really appears there before
showing it to you. I built it for people who want to revisit a long episode rather than
re-listen to it: students working through interview or lecture-style shows, and anyone who
remembers that something was said and needs to find where.

## Try it

**<https://podcast-compass.streamlit.app>**

The app sleeps after 12 hours without traffic. If you get a sleep screen, click
**"Yes, get this app back up!"** and give it about a minute.

Demo video: _link to add_

## How to use it in 30 seconds

1. Click **Load example episode**. You get a full result immediately, generated earlier and
   stored in the repository, so it costs no API call and works even if the daily limit is
   spent.
2. To use your own, paste a transcript or upload a `.txt`, `.vtt` or `.srt` file, then click
   **Generate** once.
3. Answer the quiz and press **Check answers**. Each question shows whether you were right,
   why, and the quote it came from.
4. Pick a section under **Revise one section**, choose something like *Shorter* or *Harder
   questions*, and press **Revise this section**. Only that section is regenerated; the
   rest stays exactly as it was.
5. **Undo last change** puts the previous version back. It makes no API call.
6. **Copy or download** gives you the whole result as Markdown or JSON. The copy button is
   in the top-right of the text box.

## Supported inputs and limits

| | |
|---|---|
| Formats | Pasted text, `.txt`, `.vtt`, `.srt` |
| Minimum | 250 words |
| Maximum | 150,000 characters, or 2 MB per file |
| Per session | 10 generations, with 4 seconds between them |
| Per day | 400 requests, shared by everyone using the app |

The format is detected from the content rather than the file extension, so a `.txt` file
containing subtitle markup is still read as subtitles.

**Timestamps only come from `.vtt` and `.srt` files.** They are read from the subtitle cues
by the app, never produced by the model. Plain text gets chapters with titles and no times,
and the app says so rather than inventing them.

The 250-word minimum exists because chapters have to start at increasing points in the
transcript, so a very short paste cannot produce more than one chapter. Rejecting it up
front is better than spending a request to find out.

## Run it locally

You need Python 3.11 or newer and a Gemini API key from
[Google AI Studio](https://aistudio.google.com/apikey). The free tier is enough.

### Windows, PowerShell

```powershell
git clone https://github.com/KsKarim7/Podcast-Compass.git
cd Podcast-Compass
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml      # replace your-key-here with your key, then save
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### macOS and Linux

```bash
git clone https://github.com/KsKarim7/Podcast-Compass.git
cd Podcast-Compass
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
$EDITOR .streamlit/secrets.toml      # replace your-key-here with your key, then save
./.venv/bin/python -m streamlit run app.py
```

Tested on Windows; the macOS/Linux commands are the standard equivalents.

The app opens at <http://localhost:8501>. Without a key it still runs and the example
episode still works; only generation is unavailable, and the app says so.

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```bash
./.venv/bin/python -m pytest -q
```

300 tests, no network and no API key needed — the provider is replaced by a fake. Four are
skipped on a normal run: two only apply when the pre-generated example is missing, which it
is not, and two make one real request with a deliberately invalid key to check the error
handling against the live API. Run those two with `RUN_LIVE_TESTS=1`; they spend no quota,
because the key is invalid by design.

`requirements.txt` holds the three runtime dependencies; `requirements-dev.txt` adds
`pytest`.

## Deploying

The app runs on Streamlit Community Cloud. From <https://share.streamlit.io>, create an app
pointing at this repository, branch `main`, file path `app.py`. Under **Advanced settings**,
choose a Python version and paste your key into the **Secrets** field in the same format as
`.streamlit/secrets.toml.example`:

```toml
GEMINI_API_KEY = "your-key-here"
```

**Reboot after any deploy that changes a file inside `podcast_compass/`.** Community Cloud
can pick up a new `app.py` without reloading an already-imported package module, and the two
then disagree. That happened to me: the live app raised
`AttributeError: module messages has no attribute GROUNDING_REJECTED_BECAUSE` for a constant
that existed in the deployed commit, and a reboot from **Manage app** fixed it. This cannot
be reproduced locally, because running the app locally reimports everything on restart.

A reboot or a sleep also resets the daily request counter — see below.

## Data handling and privacy

Nothing is stored. A transcript lives in the browser session's memory for as long as that
session lasts, and is never written to disk, logged, or put in a database. There is no
account system, because there is nothing to attach to an account.

The API key is read from Streamlit's secrets store in production and from a git-ignored
`.streamlit/secrets.toml` locally. It is never logged, never shown in the interface, and
never committed; what is committed is an example file with a placeholder.

**This demo runs on Gemini's free tier, and Google's terms for the unpaid tier say
submitted content is used to improve Google's products and may be read by human
reviewers.** The app shows this notice before accepting any input. Do not paste
confidential or personal material, and only use transcripts you have permission to
process.

Logs record the model used, the elapsed time, and the number of characters submitted. They
never contain transcript text or any part of the key.

## Project structure

```
app.py                  Page layout and session state
podcast_compass/        Parsing, segmentation, the model client, validation, export
tests/                  300 tests, no network required
samples/                The example episode and its pre-generated result
tools/                  Script to regenerate the example result
docs/                   Research, engineering notes, debugging log
```

- [docs/RESEARCH.md](docs/RESEARCH.md) — which model and host I chose, and why
- [docs/ENGINEERING.md](docs/ENGINEERING.md) — architecture, reliability, cost and
  maintenance
- [docs/DEBUG_LOG.md](docs/DEBUG_LOG.md) — the problems I hit and what I did about them

## Known limitations

- **The request counters reset when the app restarts.** They live in the running process's
  memory, and the host restarts the app on redeploy and after it sleeps. They guard against
  accidental overuse; they are not an enforced limit.
- **Latency near the 150,000-character limit is untested.** Measured generations took 5 to 9
  seconds on transcripts up to 2,370 characters. I have no evidence about a maximum-size
  transcript against the 45-second timeout.
- **Quote checking can drop a good item.** It forgives differences in punctuation style and
  spacing but not a changed punctuation mark, so a model that writes a dash where the
  transcript has a comma will have that item dropped rather than shown.
- **Audio is not supported**, only transcripts. The reasoning is in
  [docs/RESEARCH.md](docs/RESEARCH.md).
- **The app sleeps after 12 hours** without traffic, and the first load after that is slow.

The full version, including how incorrect output and failed requests are handled, is in
[docs/ENGINEERING.md, section D](docs/ENGINEERING.md#d-reliability-and-limitations).
