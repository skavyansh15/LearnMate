"""Runs ~22 test questions against the demo course in DEMO MODE and writes docs/EVALUATION.md.
Run: python evaluation/run_eval.py      (no API key needed; the numbers below are for the offline demo mode only)"""
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import assistant  # noqa: E402
import config  # noqa: E402
import store  # noqa: E402

# (category, question, playhead seconds, expected: 'found' | 'not_found', words one source must contain, previous question)
CASES = [
    ("before/after timestamp", "How do I add an item to a list?", 40, "not_found", [], None),
    ("before/after timestamp", "How do I add an item to a list?", 100, "found", ["append"], None),
    ("before/after timestamp", "What does pop do?", 100, "not_found", [], None),
    ("before/after timestamp", "What does pop do?", 150, "found", ["pop"], None),
    ("before/after timestamp", "How does slicing work?", 100, "not_found", [], None),
    ("before/after timestamp", "How does slicing work?", 200, "found", ["slic"], None),
    ("before/after timestamp", "What is negative indexing?", 20, "not_found", [], None),
    ("before/after timestamp", "What is negative indexing?", 70, "found", ["negative"], None),
    ("before/after timestamp", "What is a list comprehension?", 150, "not_found", [], None),
    ("before/after timestamp", "What is a list comprehension?", 240, "found", ["comprehension"], None),
    ("PDF / slide answer", "What are the arguments of insert?", 240, "found", ["insert(index", "insert(i"], None),
    ("PDF / slide answer", "How do I loop over a list with for?", 240, "found", ["for fruit", "for item", "for loop", "loop variable"], None),
    ("PDF / slide answer", "What does remove do compared to pop?", 240, "found", ["remove"], None),
    ("not in the content", "What is a dictionary?", 240, "not_found", [], None),
    ("not in the content", "How do I sort a list?", 240, "not_found", [], None),
    ("not in the content", "Who invented Python?", 240, "not_found", [], None),
    ("not in the content", "What is a tuple?", 240, "not_found", [], None),
    ("follow-up", "and how do I use it?", 100, "found", ["negative"], "What is negative indexing?"),
    ("follow-up", "what about at the front?", 130, "found", ["front", "kiwi"], "How do I add an item with insert?"),
    ("follow-up", "and does it return anything?", 160, "found", ["return"], "What does pop do?"),
]
# words that only appear in content taught later than the question's playhead (used to detect leaks)
LATER = {("How do I add an item to a list?", 40): ["append"], ("What does pop do?", 100): ["pop"],
         ("How does slicing work?", 100): ["slic"], ("What is negative indexing?", 20): ["negative"],
         ("What is a list comprehension?", 150): ["comprehension"]}


def main():
    tmp = tempfile.TemporaryDirectory()
    with mock.patch.object(config, "USERS_DIR", Path(tmp.name)), mock.patch.object(config, "LLM_API_KEY", ""):
        uid, course = store.new_uid(), store.demo_course()
        rows, lat = [], []
        for cat, q, t, expect, words, prev in CASES:
            hist = [{"role": "user", "content": prev}, {"role": "assistant", "content": "ok"}] if prev else []
            t0 = time.perf_counter()
            r = assistant.ask(uid, course, q, "video", t, hist)
            lat.append((time.perf_counter() - t0) * 1000)
            got = "found" if r["status"] == "ok" else "not_found"
            cite_ok = None
            if expect == "found" and got == "found":
                cite_ok = any(w.lower() in s["snippet"].lower() for s in r["sources"] for w in words)
            leak = any(s["time"] > t for s in r["sources"]) or any(
                w in s["snippet"].lower() for s in r["sources"] for w in LATER.get((q, t), []))
            rows.append((cat, q, t, expect, got, cite_ok, leak))

    def pct(n, d):
        return f"{n}/{d} ({100 * n // d}%)" if d else "n/a"
    found = [r for r in rows if r[3] == "found"]
    refuse = [r for r in rows if r[3] == "not_found"]
    cited = [r for r in found if r[4] == "found"]
    out = ["# Evaluation report", "",
           "**What this measures:** the offline *demo mode* (keyword search + extracted sentences, no AI service) on the shipped "
           "demo course (8 x 30 s lecture on Python lists, 4-page PDF, 6 slides), using " + str(len(rows)) + " hand-written questions. "
           "Re-create with `python evaluation/run_eval.py`.", "",
           "**What this does NOT measure:** answer quality with a real AI model (no API key / network was available when this was written), "
           "other courses, other languages, or real learners. Treat the numbers as a regression check of our logic, not as proof of accuracy.", "",
           "## Results", "", "| Metric | Result |", "|---|---|",
           f"| Questions that should be answered were answered | {pct(len(cited), len(found))} |",
           f"| Citation correctness (a shown source contains the expected fact) | {pct(sum(1 for r in cited if r[5]), len(cited))} |",
           f"| Refusal correctness (not in content / not yet watched -> 'not found') | {pct(sum(1 for r in refuse if r[4] == 'not_found'), len(refuse))} |",
           f"| Later-content leaks (a source later than the playhead, or later-only words in a source) | {sum(1 for r in rows if r[6])} of {len(rows)} |",
           f"| Average / worst response time (local, demo mode, no network) | {sum(lat) / len(lat):.1f} ms / {max(lat):.1f} ms |", "",
           "## Every case", "", "| Type | Question | Playhead | Expected | Got | Citation ok | Leak |", "|---|---|---|---|---|---|---|"]
    for cat, q, t, expect, got, cite_ok, leak in rows:
        out.append(f"| {cat} | {q} | {t}s | {expect} | {got} | {'-' if cite_ok is None else 'yes' if cite_ok else 'NO'} | {'LEAK' if leak else 'no'} |")
    out += ["", "## What the first run found", "",
            "The first run answered only 8 of 11 answerable questions: generic words such as 'over', 'compared' and 'anything' were "
            "treated as required keywords. They were added to the stop-word list in `search.py` (not special-cased per question) and the run was repeated. "
            "A second finding was a too-narrow expectation: the loop question was answered correctly from the 'loop variable' sentence, "
            "so that phrase was added to the accepted evidence for that case.", "",
            "## Known limits (found while testing)", "",
            "- Keyword search cannot match synonyms (a question that says 'delete' will not find text that says 'remove'). The AI model does not fix this, because it only sees what the search returns.",
            "- 'What did he mean here?' is only answerable in live mode (the offline demo has no language understanding).",
            "- Page unlock times for PDF/slides are set by hand in `demo_course/mapping.json`; a wrong table means a page unlocks too early or late.",
            "- Interview scores are word-matching, so a correct answer in different words can score low.",
            "- Video chunks unlock when they start, but text is cut at the playhead line by line, so a line that has not started yet is never used.", "",
            "## Still to do before claiming more", "",
            "- Run the same questions with a real AI key and record answer quality by hand.",
            "- Try 3-5 real learners on a real lecture and note where 'not found' is wrong."]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "EVALUATION.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out[:16]))


if __name__ == "__main__":
    main()
