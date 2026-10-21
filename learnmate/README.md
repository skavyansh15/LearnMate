# LearnMate AI

A beginner-friendly learning platform: **ask questions while a lecture video plays and get cited answers that never reveal anything beyond the current playback time**, study tools (summary, revision notes, quiz, concept comparison), your own PDF / PPTX / TXT documents with exact page, slide or line citations, and an adaptive text **mock interview** with an explainable scorecard.

Plain HTML + CSS + JavaScript, Python **Flask**, **PyMuPDF**, **python-pptx**, and **one** configurable AI API. No React, no database server, no vector database.

## Run it (5 minutes, no API key needed)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows      (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py                     # open http://127.0.0.1:5000
```

You start in **demo mode**: everything works offline on the built-in sample course ("Python Lists", an 8 x 30 s lecture + PDF + slides). Answers are sentences taken straight from the course text with citations.

### Turn on the real AI (optional)

1. `copy .env.example .env` (Mac/Linux: `cp`).
2. Put your key in `LLM_API_KEY=`. The defaults point at Google Gemini's OpenAI-compatible endpoint; **check the model name** in `LLM_MODEL` against your provider's current list.
3. Any OpenAI-compatible service works (OpenAI, Groq, DeepSeek, ...): change `LLM_BASE_URL` and `LLM_MODEL`. Nothing else changes.
4. Restart. The badge in the top bar changes to "AI live".

## What to try (2-minute demo script)

1. Open the demo course. Play to ~0:40, pause, ask **"How do I add an item to a list?"** -> *Not found in the content so far* (it is taught at 1:30).
2. Play past 1:40 and ask again -> a cited answer. Click the yellow citation to jump the video to that moment.
3. **Study** tab -> *Revision notes*, *Quiz me*, and *Compare* "remove" vs "pop".
4. **Add your own course** (title only), upload a PDF/PPTX/TXT in **Documents**, ask about it: citations read like `notes.pdf p.3` / `deck.pptx slide 5` / `notes.txt lines 12-20`.
5. **Interview** tab -> answer 4 questions; try a weak answer to see the follow-up, a strong one to see a harder question, then read the scorecard ("How was this scored?").

## How the key promises are kept

| Promise | How |
|---|---|
| Never reveals content beyond the playhead | The time filter runs **before** search. Video text is cut line-by-line at the playhead, so a line that has not started is never searched or sent to the AI. Tested at 7 playhead positions x 7 questions. |
| Never invents citations | Sources shown are the retrieved chunks. Citation numbers the AI makes up are dropped; an answer with no valid citation becomes "not found". |
| Missing evidence is handled | No chunk with enough of the question's key words -> "not found", **without calling the AI** (also saves money). |
| Protect the API key | Only read from environment / `.env` (git-ignored), never sent to the browser, scrubbed from error messages. |
| Validate uploads | Extension + real file signature, size/page/text limits, zip-bomb check, nothing is stored except extracted text. |
| Control AI cost | Max tokens, evidence capped at 6000 characters, identical requests cached, per-user daily AI call limit (then demo answers), per-minute rate limit, one interview feedback call at most. |
| Users' files stay separate | Each browser gets a random anonymous id; data lives in `data/users/<id>/`; ids are validated against path tricks; tested with two users. |

## Project map

```
app.py          Flask routes (thin)            assistant.py  Q&A, summary, notes, quiz, compare
interview.py    mock interview + scorecard     search.py     tiny BM25 keyword search
ingest.py       SRT/VTT, PDF, PPTX, TXT -> chunks + upload validation
llm.py          the ONLY file that calls an AI service      store.py  JSON files, progress, limits
static/         index.html, style.css, app.js   demo_course/ sample data     tools/make_demo.py  rebuild it
tests/          72 automated tests              evaluation/   run_eval.py -> docs/EVALUATION.md
docs/           ARCHITECTURE, API, EVALUATION, DEPLOYMENT
```

Run the tests: `python -m unittest discover -s tests` (no API key, no internet needed).

## Using your own lecture

Dashboard -> **Add your own course**: a direct `.mp4`/`.webm` link (YouTube page links do not work) plus a matching `.srt` or `.vtt` transcript. Timestamps must line up with the video. Automatic transcription and direct video upload are **not** included.

## Honest limits

- **Uploaded PDFs/slides are not tied to the video timeline.** They are searched in the *Documents* tab. Only the demo course has PDF/slide pages unlocked at video times (`demo_course/mapping.json`, set by hand).
- Search is keyword-based (no synonyms): "delete" will not find text that says "remove".
- Demo-mode answers are extracted sentences, not written explanations. The interview score is word-matching, so a correct answer in different words can score low. The scorecard says so.
- Scanned PDFs / image-only slides have no text (no OCR). YouTube links, login/accounts, and payments are not included.
- Data is stored in local JSON files: fine for a demo, not for thousands of users.

## What is verified (and what is not)

Verified here: 72 automated tests pass; the server was run and all endpoints exercised over real HTTP in demo mode; demo-mode evaluation in `docs/EVALUATION.md`.
**Not verified:** answer quality with a real AI model (calls are mocked in tests), reading real PDFs with PyMuPDF (the library was not installable where this was built: the page/label logic is tested with a stand-in and one test runs automatically once PyMuPDF is installed, plus the demo PDF's text was cross-checked with `pdftotext`), the UI in a real browser / on a phone (JavaScript was syntax-checked only), and deployment to a host. Run the tests and click through the demo script on your machine before presenting.
