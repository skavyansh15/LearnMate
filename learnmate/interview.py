"""Text mock interview. Questions come from the course; the SCORE is rule-based so it is explainable:
each question has key points, and the score is the share of key points your answer mentions.
Adaptive: a weak answer gets one follow-up about a missed point; a strong answer moves to a harder question."""
import json
import re

import config
import llm
import search
import store
from errors import UserError

SYSTEM_IV = """You write interview questions using ONLY the numbered context. Reply with JSON only:
{"questions":[{"question":"...","level":"easy","key_points":[{"name":"short phrase","terms":["word1","word2"]}]}]}
"level" is easy or hard. Each question has 2-4 key points; "terms" are words a correct answer would likely contain."""
SYSTEM_FB = "You are a kind interviewer. Write 2-3 sentences of feedback from the scorecard. Do not change any scores."


# ---------- matching -----------------------------------------------------------
def term_hit(term, answer_lower, answer_stems):
    term = term.lower().strip()
    if not term:
        return False
    if re.search(r"[^a-z0-9 ]", term):  # symbols such as '[' or ':' -> plain text match
        return term in answer_lower
    return all(search.stem(w) in answer_stems for w in term.split())


def score_answer(question, answer):
    low = answer.lower()
    stems = set(search.stem(w) for w in re.findall(r"[a-z0-9]+", low))
    covered, missed = [], []
    for kp in question["key_points"]:
        (covered if any(term_hit(t, low, stems) for t in kp["terms"]) else missed).append(kp["name"])
    return covered, missed


# ---------- questions ----------------------------------------------------------
def demo_questions(course, n):
    """Offline questions: one per spread-out piece of the course, key points = its most characteristic words."""
    pieces = [c["text"] for c in course["chunks"] if len(c["text"].split()) >= 12]
    if len(pieces) < n:  # small course: use single sentences instead
        pieces = [x for c in course["chunks"] for x in search.sentences(c["text"]) if len(x.split()) >= 8]
    step = max(1, len(pieces) // n)
    out = []
    for i, text in enumerate(pieces[::step][:n]):
        terms = search.top_terms([text], 4)[:3]
        if len(terms) < 2:
            continue
        out.append({"question": f"What does the material say about {', '.join(terms[:-1])} and {terms[-1]}?",
                    "level": "easy" if i < (n + 1) // 2 else "hard",
                    "key_points": [{"name": t, "terms": [t]} for t in terms]})
    return out


def parse_questions(text):
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    m = re.search(r"(\{|\[).*(?:\}|\])", clean, re.S)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(0))
        if isinstance(parsed, dict):
            raw = parsed.get("questions", [])
        elif isinstance(parsed, list):
            raw = parsed
        else:
            raw = []
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        try:
            kps_raw = q.get("key_points", [])
            kps = [{"name": str(k.get("name", ""))[:60], "terms": [str(t)[:30] for t in k.get("terms", [])][:6]}
                   for k in kps_raw if isinstance(k, dict)][:4]
            if str(q.get("question", "")).strip() and len(kps) >= 2 and all(k["terms"] for k in kps):
                out.append({"question": str(q["question"])[:300], "level": "hard" if q.get("level") == "hard" else "easy", "key_points": kps})
        except (KeyError, TypeError):
            continue
    return out


def load_questions(uid, course, n, api_key=None, base_url=None, model=None):
    eff_key = api_key or config.LLM_API_KEY
    if llm.is_live(eff_key) and store.allow_ai_call(uid):
        items = [{"n": i + 1, "label": c.get("label", ""), "text": c["text"]} for i, c in enumerate(course.get("chunks", [])[:40])]
        ctx = "\n\n".join(f"[{i['n']}] {i['text']}" for i in items)[:config.CONTEXT_CHARS]
        try:
            prompt = (
                f"Context from course:\n{ctx}\n\n"
                f"Task: Generate {n} realistic interview questions based directly on this material. "
                "Include 2-4 key point concepts and likely vocabulary terms for each question. "
                "Return JSON ONLY matching the required format."
            )
            qs = parse_questions(llm.complete(SYSTEM_IV, prompt, config.MAX_TOKENS_STUDY, api_key=eff_key, base_url=base_url, model=model))
            if qs:
                return qs, "live"
        except UserError:
            pass
    bank = config.DEMO_DIR / "interview_bank.json"
    if course["id"] == store.DEMO_ID and bank.exists():
        return json.loads(bank.read_text(encoding="utf-8")), "demo"
    return demo_questions(course, n), "demo"


def pick_next(state):
    want = state["difficulty"]
    pool = [i for i in range(len(state["questions"])) if i not in state["asked"]]
    pool.sort(key=lambda i: state["questions"][i]["level"] != want)  # preferred level first
    return pool[0] if pool else None


# ---------- session flow -------------------------------------------------------
def start(uid, course, n=4, api_key=None, base_url=None, model=None):
    n = max(2, min(int(n or 4), 6))
    questions, mode = load_questions(uid, course, n, api_key=api_key, base_url=base_url, model=model)
    if len(questions) < 2:
        raise UserError("not_enough_content", "Not enough content for an interview yet.",
                        "Add a document or watch more of the video, then try again.")
    state = {"id": store.new_id(), "course_id": course["id"], "mode": mode, "questions": questions, "total": min(n, len(questions)),
             "asked": [], "difficulty": "easy", "current": None, "follow_up_used": False, "log": [], "done": False}
    if api_key:
        state["api_key"] = api_key
    if base_url:
        state["base_url"] = base_url
    if model:
        state["model"] = model
    state["current"] = pick_next(state)
    state["asked"].append(state["current"])
    store.save_obj(uid, "interviews", state)
    return _view(state, f"Question 1 of {state['total']}")


def _view(state, note=""):
    q = state["questions"][state["current"]]
    return {"interview_id": state["id"], "question": state["pending_follow_up"] if state.get("pending_follow_up") else q["question"],
            "is_follow_up": bool(state.get("pending_follow_up")), "number": len(state["log"]) + 1,
            "total": state["total"], "level": q["level"], "note": note, "mode": state["mode"]}


def answer(uid, interview_id, text):
    state = store.load_obj(uid, "interviews", interview_id)
    if state["done"]:
        raise UserError("finished", "This interview is finished.", "Open the scorecard or start a new one.")
    text = (text or "").strip()
    if len(text) < 3:
        raise UserError("empty_answer", "Please type an answer first.")
    if len(text) > 2000:
        raise UserError("too_long", "Answers can have at most 2000 characters.")
    q = state["questions"][state["current"]]
    entry = state.setdefault("current_entry", {"question": q["question"], "level": q["level"], "answers": [], "follow_up": None})
    entry["answers"].append(text)
    covered, missed = score_answer(q, " ".join(entry["answers"]))
    entry["covered"], entry["missed"] = covered, missed
    score = len(covered) / len(q["key_points"])
    feedback = ""
    if score < 0.6 and not state["follow_up_used"] and missed:  # ADAPT 1: follow-up on a missed point
        state["follow_up_used"] = True
        state["pending_follow_up"] = f"You did not mention '{missed[0]}'. Can you add how it fits in?"
        entry["follow_up"] = missed[0]
        store.save_obj(uid, "interviews", state)
        return {**_view(state, "Follow-up"), "feedback": f"Covered so far: {', '.join(covered) or 'nothing yet'}."}
    # question finished -> log it
    entry["score"] = round(score, 2)
    state["log"].append(entry)
    state.pop("current_entry", None)
    state.pop("pending_follow_up", None)
    state["follow_up_used"] = False
    state["difficulty"] = "hard" if score >= 0.8 else "easy"  # ADAPT 2: harder after a strong answer
    feedback = f"Covered: {', '.join(covered) or 'none'}. Missed: {', '.join(missed) or 'none'}."
    nxt = pick_next(state) if len(state["log"]) < state["total"] else None
    if nxt is None:
        state["done"] = True
        store.save_obj(uid, "interviews", state)
        return {"finished": True, "feedback": feedback, "interview_id": state["id"]}
    state["current"] = nxt
    state["asked"].append(nxt)
    store.save_obj(uid, "interviews", state)
    note = f"Question {len(state['log']) + 1} of {state['total']}" + (" (harder - nice work)" if state["difficulty"] == "hard" else "")
    return {**_view(state, note), "feedback": feedback}


def scorecard(uid, interview_id, api_key=None, base_url=None, model=None):
    state = store.load_obj(uid, "interviews", interview_id)
    if not state["done"]:
        raise UserError("not_finished", "Finish the interview first.", "Answer all questions to see the scorecard.")
    log = state["log"]
    overall = round(100 * sum(e["score"] for e in log) / len(log))
    level = "Strong" if overall >= 80 else "Developing" if overall >= 50 else "Needs more study"
    strengths = sorted({k for e in log for k in e["covered"]})
    gaps = sorted({k for e in log for k in e["missed"]})
    fu = [e for e in log if e["follow_up"]]
    recovered = sum(1 for e in fu if e["follow_up"] in e["covered"])
    card = {"overall_percent": overall, "level": level, "mode": state["mode"],
            "questions": [{"question": e["question"], "level": e["level"], "score_percent": round(100 * e["score"]),
                           "covered": e["covered"], "missed": e["missed"], "follow_up_on": e["follow_up"],
                           "answer_words": sum(len(a.split()) for a in e["answers"])} for e in log],
            "strengths": strengths, "gaps": gaps,
            "follow_up_recovery": f"{recovered} of {len(fu)} follow-ups fixed the missing point" if fu else "No follow-ups were needed",
            "how_scored": "Each question has key points taken from the course. Question score = key points your answer mentioned / total "
                          "key points. Overall = average of question scores. Follow-up answers are added to the first answer. "
                          "The score is rule-based (word matching), so a correct answer in very different words can score low."}
    if "summary" not in state:
        summary = f"You scored {overall}% ({level}). " + (f"Review: {', '.join(gaps[:4])}." if gaps else "No gaps found.")
        eff_key = api_key or state.get("api_key") or config.LLM_API_KEY
        eff_url = base_url or state.get("base_url") or config.LLM_BASE_URL
        eff_model = model or state.get("model") or config.LLM_MODEL
        if llm.is_live(eff_key) and store.allow_ai_call(uid):
            try:
                summary = llm.complete(SYSTEM_FB, json.dumps({k: card[k] for k in ("overall_percent", "strengths", "gaps")}), 150,
                                       api_key=eff_key, base_url=eff_url, model=eff_model)
            except UserError:
                pass
        state["summary"] = summary
        store.save_obj(uid, "interviews", state)
        store.update_progress(uid, state["course_id"], lambda rec: rec["interviews"].append(overall))
    card["feedback"] = state["summary"]
    return card
