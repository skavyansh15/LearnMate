"""The learning assistant: grounded answers, summaries, notes, quizzes, comparisons.
Rules: (1) the AI only sees evidence the learner is allowed to see, (2) sources shown to the learner are the
retrieved chunks - never ones the AI names on its own, (3) no evidence = 'not found'."""
import json
import random
import re

import config
import llm
import search
import store
from errors import UserError

NOT_FOUND_TEXT = "Not found in the content so far."
REFERRING = re.compile(r"\b(here|this|that|just|mean|meant|said|again|repeat|previous)\b", re.I)
OVERVIEW_RE = re.compile(r"\b(summariz|summary|key points|covered so far|what was just covered|core concept|core mechanism|overview|recap|review|explain current topic|explain what was covered)\b", re.I)
# A citation is [n] NOT glued to a word, so code like fruits[1] in the course text is never mistaken for one.
CITE = re.compile(r"(?<![\w\)])\[(\d+(?:\s*,\s*\d+)*)\]")

SYSTEM_QA = """You are LearnMate, a dedicated AI Course Tutor Chatbot.
Your boundaries are STRICTLY limited to the provided course context and what the learner has watched up to their current timestamp.

CRITICAL RULES:
1. ONLY answer from the provided course context and evidence watched up to the current playback time.
2. If the user asks about something that occurs AFTER the current playback time or is NOT in the course materials, POLITELY DECLINE. Tell them: "That hasn't been covered yet in what you've watched so far! Please keep watching the video to reach this topic."
3. NEVER make up facts, and NEVER answer off-topic general knowledge questions outside this course.
4. Smart citations: Cite ONLY the specific 1 or 2 context snippets (e.g. [1]) that directly contain the evidence for your statement. Do NOT cite every available snippet, and do not repeat citations unnecessarily.
5. Format your response cleanly using standard markdown: use bold (**term**) for emphasis, bullet points (-) for key items, and backticks (`code`) for code. If using section titles, use ### Title.
6. Be warm, conversational, encouraging, and clear (2-4 sentences). Answer follow-up questions naturally."""

SYSTEM_STUDY = """You are LearnMate, a study helper. Use ONLY the numbered context up to the watched timestamp. Cite sources like [1] after each point.
If the context is not enough for a point, leave that point out. Do not invent facts."""

SYSTEM_QUIZ = """You are an expert educational examiner. Carefully analyze the provided course context up to the learner's current watch time.
Select the MOST IMPORTANT, test-worthy concepts that were actually taught and create engaging multiple-choice questions.

Reply with JSON ONLY (no markdown fences, no extra text):
{"questions":[{"q":"Clear conceptual question?","options":["Option A","Option B","Option C","Option D"],"answer":0,"explanation":"Why this is correct based on the lecture","source":1}]}
- "answer" must be the 0-based index (0, 1, 2, or 3) of the correct option.
- "source" must be the context number (e.g. 1, 2) that proves the answer."""


def fmt(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def not_found(text=NOT_FOUND_TEXT):
    return {"status": "not_found", "answer": text, "sources": [], "mode": "demo" if not llm.is_live() else "live"}


def clean_question(q):
    q = (q or "").strip()
    if not q:
        raise UserError("empty_question", "Please type a question.")
    if len(q) > config.MAX_QUESTION_CHARS:
        raise UserError("too_long", f"Questions can have at most {config.MAX_QUESTION_CHARS} characters.")
    return q


# ---------- what the learner may see -----------------------------------------
def visible_chunks(course, scope, t):
    """video scope: only content unlocked up to playback time t.  docs scope: the learner's own uploaded files.
    For YouTube videos the time gate is relaxed because currentTime cannot be read reliably via the IFrame API."""
    if scope == "video":
        if not course.get("has_video"):
            raise UserError("no_video", "This course has no video.", "Use the Documents tab instead.")
        doc_chunks = [c for c in course.get("chunks", []) if c.get("unlock") is None]
        if not course.get("cues"):
            if doc_chunks:
                return doc_chunks
            raise UserError("no_transcript", "This video has no transcript uploaded.",
                            "Upload a transcript or document to ask questions.")
        if t is None or t < 0:
            raise UserError("bad_time", "current_time is required for video questions.")
        # Strictly enforce playback time cutoff for all video types (including YouTube)
        video_chunks = [c for c in course["chunks"] if c.get("unlock") is not None and c["unlock"] <= t]
        # Include documents unlocked from the start so learners can ask about course materials
        return video_chunks + doc_chunks
    if scope == "docs":
        return [c for c in course.get("chunks", []) if c.get("unlock") is None]
    raise UserError("bad_scope", "scope must be 'video' or 'docs'.")


def to_item(c, course, scope, t):
    text, label = c["text"], c.get("label", "")
    if c["type"] == "video":
        t_val = t if (t is not None) else c["end"]
        end = min(c["end"], t_val)
        label = f"Video {fmt(c['start'])}-{fmt(end)}"
        if c["end"] > t_val:  # chunk still in progress: keep only lines that already started
            text = " ".join(q["text"] for q in course.get("cues", []) if c["start"] <= q["start"] <= t_val)
    return {"type": c["type"], "label": label, "time": c.get("unlock") if scope == "video" else None, "text": text}


def local_window(course, t):
    got = [c for c in course.get("cues", []) if t - config.WINDOW_S <= c["start"] <= t]
    if not got:
        return None
    return {"type": "video", "label": f"Video {fmt(got[0]['start'])}-{fmt(min(got[-1]['end'], t))} (just now)",
            "time": got[0]["start"], "text": " ".join(c["text"] for c in got)}


def number(items):
    for i, it in enumerate(items, 1):
        it["n"] = i
    return items


def context_text(items, cap=None):
    out, used = [], 0
    for it in items:
        piece = f"[{it['n']}] ({it['label']}) {it['text']}"
        if used + len(piece) > (cap or config.CONTEXT_CHARS):
            break
        out.append(piece)
        used += len(piece)
    return "\n\n".join(out)


def generate(uid, system, user, max_tokens, demo_fn, api_key=None, base_url=None, model=None):
    """Live AI when configured and within the daily budget, otherwise (or on error) the offline demo answer."""
    warning = None
    if llm.is_live(api_key):
        if store.allow_ai_call(uid):
            try:
                return llm.complete(system, user, max_tokens, api_key=api_key, base_url=base_url, model=model), "live", None
            except UserError as e:
                warning = f"{e.message} Showing a demo-mode answer instead."
        else:
            warning = "Daily AI limit reached - showing a demo-mode answer instead."
    return demo_fn(), "demo", warning


NOT_FOUND_TEXT = "That hasn't been covered yet in what you've watched so far! Please keep watching the video to reach this topic."


def not_found(text=NOT_FOUND_TEXT):
    return {"status": "not_found", "answer": text, "sources": [], "mode": "demo" if not llm.is_live() else "live"}


def verify(raw, items, allow_uncited=False):
    """Keep citations that point at retrieved evidence. If the AI politely declines or answers without citations, handle naturally."""
    raw = (raw or "").strip()
    if not raw or "NOT_FOUND" in raw:
        return not_found()
    # Normalize common LLM citation variants like (Source 1), [Source 1], (Ref 1), (1) to [1]
    raw = re.sub(r"(?:\[|\()(?:Source|Context|Ref|Evidence)\s*(\d+)(?:\]|\))", r"[\1]", raw, flags=re.I)
    raw = re.sub(r"\((?:source\s*)?(\d+)\)", r"[\1]", raw, flags=re.I)
    valid = {it["n"]: it for it in items}
    cited = []

    def fix(m):
        good = [n for n in (int(x) for x in re.split(r"\s*,\s*", m.group(1))) if n in valid]
        cited.extend(n for n in good if n not in cited)
        return "".join(f"[{n}]" for n in good)

    text = CITE.sub(fix, raw)
    # If the response is a polite boundary declination, deliver it as friendly chatbot message
    if not cited:
        if any(phrase in raw.lower() for phrase in ["hasn't been covered", "not covered yet", "keep watching", "outside", "after the current"]):
            return {"status": "not_found", "answer": raw, "sources": []}
        if allow_uncited and len(raw) >= 15:
            # If model produced a genuine summary but omitted explicit [n] bracket tags,
            # present the summary and attach representative sources from the retrieved context.
            default_sources = [{"n": it["n"], "type": it["type"], "label": it["label"], "time": it["time"],
                                "snippet": it.get("snippet") or it["text"][:140]} for it in items[:2]]
            return {"status": "ok", "answer": text, "sources": default_sources}
        return not_found()
    selected_cited = cited[:3]
    return {"status": "ok", "answer": text, "sources": [
        {"n": n, "type": valid[n]["type"], "label": valid[n]["label"], "time": valid[n]["time"],
         "snippet": valid[n].get("snippet") or valid[n]["text"][:140]} for n in selected_cited]}


def finish(result, mode, warning):
    result["mode"] = mode
    if warning:
        result["warning"] = warning
    return result


# ---------- Q&A ---------------------------------------------------------------
def demo_answer(items, question):
    q = set(search.tokens(question))
    picks = []
    for it in items:
        for s in search.sentences(it["text"]):
            score = len(q & set(search.tokens(s))) if len(s.split()) >= 4 else 0
            if score:
                picks.append((-score, it["n"], s))
    picks.sort()
    best = []
    for _, n, s in picks:
        if all(s != b[1] for b in best):
            best.append((n, s))
        if len(best) == 1:  # one clear sentence beats two loosely related ones
            break
    return " ".join(f"{s} [{n}]" for n, s in best) or "NOT_FOUND"


def ask(uid, course, question, scope, t, history, api_key=None, base_url=None, model=None):
    question = clean_question(question)
    chunks = _evidence(course, scope, t)  # text already cut at the playhead, so unplayed lines cannot match
    hits = search.search(chunks, question, 4)
    topic = question  # the words that found the evidence (used by the offline answer too)
    prev = [m["content"] for m in history if m.get("role") == "user"]
    if not hits and prev:  # follow-up like "and how do I use it?"
        topic = prev[-1] + " " + question
        hits = search.search(chunks, topic, 4)
    items = [dict(h) for h in hits]
    if scope == "video" and len(items) < 2:
        window = local_window(course, t)
        if window:
            items.append(window)
    if not hits and OVERVIEW_RE.search(question) and chunks:
        # User requested a summary/overview of covered progress or core concept
        hits = chunks[-4:] if len(chunks) > 4 else chunks
        items = [dict(h) for h in hits]
        topic = " ".join(search.top_terms([c["text"] for c in hits], 6))
    if not items or (not hits and not REFERRING.search(question) and not OVERVIEW_RE.search(question)):
        return not_found()  # no evidence -> we do not even call the AI
    number(items)
    for it in items:
        it["snippet"] = search.excerpt(it["text"], topic, size=140)  # preview starts at the best-matching sentence
    strip = lambda text: CITE.sub("", text).strip()[:300]
    hist = "\n".join(f"{m['role']}: {strip(m['content'])}" for m in history[-4:])
    prompt = f"Context:\n{context_text(items)}\n\n" + (f"Earlier chat:\n{hist}\n\n" if hist else "") + f"Question: {question}"
    raw, mode, warn = generate(uid, SYSTEM_QA, prompt, config.MAX_TOKENS_ANSWER, lambda: demo_answer(items, topic), api_key=api_key, base_url=base_url, model=model)
    return finish(verify(raw, items), mode, warn)


# ---------- summary / notes / compare ----------------------------------------
def _evidence(course, scope, t):
    chunks = visible_chunks(course, scope, t)
    return number([to_item(c, course, scope, t) for c in chunks])


def demo_summary(items, notes):
    step = max(1, len(items) // 6)
    bullets = []
    for it in items[::step][:6]:
        bullets.append(f"- {search.lead(it['text'])} [{it['n']}]")
    if not notes:
        return "\n".join(bullets)
    terms = ", ".join(search.top_terms([i["text"] for i in items], 8))
    checks = "\n".join(f"- What does the material say about {w}?" for w in search.top_terms([i["text"] for i in items], 3))
    return f"Key terms: {terms}\n\nMain points:\n" + "\n".join(bullets) + f"\n\nCheck yourself:\n{checks}"


def study(uid, course, kind, scope, t, a=None, b=None, api_key=None, base_url=None, model=None):
    if kind in ("summary", "notes"):
        items = _evidence(course, scope, t)
        if not items and scope == "video" and (t is None or t <= 0):
            all_chunks = [c for c in course.get("chunks", []) if c.get("type") == "video"]
            if all_chunks:
                items = number([to_item(c, course, scope, None) for c in all_chunks[:config.TOP_K]])
        if not items:
            return not_found("Nothing to summarize yet - watch more of the video or upload a document first.")
        ask_for = ("Write 4-6 bullet points summarizing the context." if kind == "summary" else
                   "Write revision notes with three parts: 'Key terms' (term: meaning), 'Main points' (bullets), "
                   "'Check yourself' (3 short questions).")
        prompt = f"Context:\n{context_text(items)}\n\n{ask_for} Cite [n] after each point."
        raw, mode, warn = generate(uid, SYSTEM_STUDY, prompt, config.MAX_TOKENS_STUDY, lambda: demo_summary(items, kind == "notes"), api_key=api_key, base_url=base_url, model=model)
        return finish(verify(raw, items, allow_uncited=True), mode, warn)
    if kind == "compare":
        a, b = (a or "").strip()[:60], (b or "").strip()[:60]
        if not a or not b:
            raise UserError("bad_request", "Give two concepts to compare.", "Fill in both boxes.")
        chunks = _evidence(course, scope, t)
        ha, hb = search.search(chunks, a, 2), search.search(chunks, b, 2)
        merged = ha + [x for x in hb if x not in ha]
        items = number([dict(h) for h in merged])
        if not items:
            return not_found(f"Nothing about '{a}' or '{b}' was found in the content so far.")
        na = [i + 1 for i, c in enumerate(merged) if c in ha]   # evidence numbers for concept A
        nb = [i + 1 for i, c in enumerate(merged) if c in hb]   # evidence numbers for concept B
        missing = [name for name, ev in ((a, na), (b, nb)) if not ev]
        prompt = (f"Context:\n{context_text(items)}\n\nCompare '{a}' (evidence {na or 'none'}) and '{b}' (evidence {nb or 'none'}). "
                  "Give: Similarities, Differences, When to use each. If a concept has no evidence say so. Cite [n].")

        def demo():
            line = lambda name, ns: f"{name}: " + (" ".join(f"{search.best_sentence(items[n - 1]['text'], name)} [{n}]" for n in ns[:2]) if ns else "no evidence found yet.")
            return line(a, na) + "\n\n" + line(b, nb)

        raw, mode, warn = generate(uid, SYSTEM_STUDY, prompt, config.MAX_TOKENS_STUDY, demo, api_key=api_key, base_url=base_url, model=model)
        res = finish(verify(raw, items, allow_uncited=True), mode, warn)
        if missing and res["status"] == "ok":
            res["warning"] = (res.get("warning", "") + f" No evidence found for: {', '.join(missing)}.").strip()
        return res
    raise UserError("bad_request", "kind must be summary, notes or compare.")


# ---------- quiz ---------------------------------------------------------------
def parse_quiz(text, items, n):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(m.group(0))["questions"] if m else []
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for q in raw:
        try:
            ok = (isinstance(q["q"], str) and len(q["options"]) == 4 and all(isinstance(o, str) for o in q["options"])
                  and int(q["answer"]) in range(4) and int(q["source"]) in range(1, len(items) + 1))
        except (KeyError, TypeError, ValueError):
            continue
        if ok:  # questions that cite evidence we do not have are dropped
            out.append({"q": q["q"], "options": q["options"], "answer": int(q["answer"]),
                        "explanation": str(q.get("explanation", ""))[:300], "source": int(q["source"])})
    return out[:n]


def demo_quiz(items, n, rng):
    terms = search.top_terms([i["text"] for i in items], 40)
    termset, used, qs = set(terms), set(), []
    pool = items[:]
    rng.shuffle(pool)
    for it in pool:
        for s in search.sentences(it["text"]):
            if not 6 <= len(s.split()) <= 30 or re.search(r"[()\[\]=:]", s):  # skip code-like lines
                continue
            cand = [w for w in re.findall(r"[A-Za-z]+", s) if w.lower() in termset and w.lower() not in used]
            if not cand:
                continue
            ans = max(cand, key=len).lower()
            distract = [t for t in terms if t != ans and t not in s.lower()]
            if len(distract) < 3:
                continue
            rng.shuffle(distract)
            options = [ans] + distract[:3]
            rng.shuffle(options)
            qs.append({"q": "Fill in the blank: " + re.sub(re.escape(ans), "_____", s, count=1, flags=re.I),
                       "options": options, "answer": options.index(ans),
                       "explanation": f"The material says: {s}", "source": it["n"]})
            used.add(ans)
            break
        if len(qs) >= n:
            break
    return qs


def make_quiz(uid, course, scope, t, n=5, api_key=None, base_url=None, model=None):
    n = max(1, min(int(n or 5), 10))
    items = _evidence(course, scope, t)
    if not items and scope == "video" and (t is None or t <= 0):
        all_chunks = [c for c in course.get("chunks", []) if c.get("type") == "video"]
        if all_chunks:
            items = number([to_item(c, course, scope, None) for c in all_chunks[:config.TOP_K]])
    if not items:
        return not_found("Nothing to quiz on yet - watch more of the video or upload a document first.")
    qid = store.new_id()
    rng = random.Random(qid)
    prompt = (
        f"Context (covered content up to watched position):\n{context_text(items)}\n\n"
        f"Task: Select the {n} most important core concepts taught in this context and write {n} challenging, educational multiple-choice quiz questions. "
        "Test real understanding, not just trivia. Return JSON strictly matching the requested format."
    )
    raw, mode, warn = generate(uid, SYSTEM_QUIZ, prompt, config.MAX_TOKENS_STUDY, lambda: json.dumps({"questions": demo_quiz(items, n, rng)}), api_key=api_key, base_url=base_url, model=model)
    qs = parse_quiz(raw, items, n)
    if not qs and mode == "live":  # AI gave unusable JSON -> fall back to offline questions
        qs, mode, warn = demo_quiz(items, n, rng), "demo", "The AI's quiz was unusable, so offline questions were used."
    if not qs:
        return not_found("Not enough content yet to make quiz questions.")
    for q in qs:
        it = items[q["source"] - 1]
        q["source"] = {"label": it["label"], "time": it["time"], "snippet": it["text"][:220]}
    store.save_obj(uid, "quizzes", {"id": qid, "course_id": course["id"], "questions": qs})
    public = [{"q": q["q"], "options": q["options"]} for q in qs]
    return finish({"status": "ok", "quiz_id": qid, "questions": public}, mode, warn)


def grade_quiz(uid, quiz_id, answers):
    quiz = store.load_obj(uid, "quizzes", quiz_id)
    qs = quiz["questions"]
    if not isinstance(answers, list) or len(answers) != len(qs):
        raise UserError("bad_request", "Send one answer per question.")
    results = []
    for q, a in zip(qs, answers):
        results.append({"correct": a == q["answer"], "answer": q["answer"], "explanation": q["explanation"], "source": q["source"]})
    score = sum(r["correct"] for r in results)
    store.update_progress(uid, quiz["course_id"], lambda rec: rec["quizzes"].append({"score": score, "total": len(qs)}))
    return {"score": score, "total": len(qs), "results": results}
