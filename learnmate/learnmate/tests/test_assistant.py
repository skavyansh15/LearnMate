import json
import unittest
from unittest import mock

from helpers import Base, config, DEMO
import assistant
import llm
import store
from errors import UserError

QUESTIONS = ["how do I add an item to a list", "what is negative indexing", "what does pop do", "how does slicing work",
             "what is a list comprehension", "how do I loop over a list", "what is a dictionary"]


class GatingTests(Base):
    def ask(self, q, t, history=None, scope="video"):
        return assistant.ask(self.uid, self.demo, q, scope, t, history or [])

    def test_nothing_after_the_playhead_is_ever_a_source(self):
        for t in (0, 20, 45, 95, 130, 170, 215, 240):
            for q in QUESTIONS:
                r = self.ask(q, t)
                for s in r["sources"]:
                    self.assertLessEqual(s["time"], t, f"{q!r} at {t}s leaked {s['label']}")

    def test_same_question_before_and_after_the_topic(self):
        self.assertEqual(self.ask("how do I add an item to a list", 40)["status"], "not_found")
        r = self.ask("how do I add an item to a list", 100)
        self.assertEqual(r["status"], "ok")
        self.assertIn("append", r["answer"])

    def test_unknown_topic_is_not_found(self):
        r = self.ask("what is a dictionary", 240)
        self.assertEqual((r["status"], r["sources"]), ("not_found", []))

    def test_ai_never_receives_later_content(self):
        m = self.live("The answer [1].")
        self.ask("how do I add an item with append", 100)
        prompt = m.call_args[0][1]
        self.assertNotIn("slicing", prompt.lower())          # taught at 150 s
        self.assertNotIn("takes an index", prompt)           # second half of the 90-120 s chunk (cue starts at 105 s)
        self.assertIn("append", prompt)

    def test_follow_up_uses_previous_question(self):
        h = [{"role": "user", "content": "what is negative indexing"}, {"role": "assistant", "content": "x"}]
        r = self.ask("and how do I use it", 100, h)
        self.assertEqual(r["status"], "ok")

    def test_docs_scope_never_returns_video_gated_pages(self):
        r = assistant.ask(self.uid, self.demo, "how does slicing work", "docs", None, [])
        self.assertEqual(r["status"], "not_found")

    def test_bad_input(self):
        for q in ("", "x" * 501):
            with self.assertRaises(UserError):
                self.ask(q, 10)
        with self.assertRaises(UserError):
            assistant.ask(self.uid, self.demo, "hi", "video", None, [])


class VerifyTests(Base):
    items = [{"n": 1, "type": "video", "label": "Video 0:00-0:30", "time": 0, "text": "Lists use fruits[1] to read items."},
             {"n": 2, "type": "pdf", "label": "a.pdf p.2", "time": 60, "text": "More text."}]

    def test_invented_sources_are_dropped(self):
        r = assistant.verify("Fact [1][9].", self.items)
        self.assertEqual([s["n"] for s in r["sources"]], [1])
        self.assertNotIn("[9]", r["answer"])

    def test_no_valid_citation_means_not_found(self):
        for raw in ("Fact without source.", "Fact [7].", "NOT_FOUND", ""):
            self.assertEqual(assistant.verify(raw, self.items)["status"], "not_found")

    def test_code_in_text_is_not_mistaken_for_a_citation(self):
        r = assistant.verify("Use fruits[1] to read the second item [1].", self.items)
        self.assertIn("fruits[1]", r["answer"])

    def test_comma_citations_are_normalised(self):
        r = assistant.verify("Both [1, 2].", self.items)
        self.assertEqual(r["answer"], "Both [1][2].")


class ModeTests(Base):
    def test_demo_mode_needs_no_key(self):
        r = assistant.ask(self.uid, self.demo, "what does pop do", "video", 150, [])
        self.assertEqual((r["status"], r["mode"]), ("ok", "demo"))

    def test_live_mode_uses_ai_and_verifies_its_citations(self):
        self.live("Pop removes by position [1][8].")
        r = assistant.ask(self.uid, self.demo, "what does pop do", "video", 150, [])
        self.assertEqual(r["mode"], "live")
        self.assertNotIn("[8]", r["answer"])

    def test_ai_error_falls_back_to_demo_with_warning(self):
        self.live()
        with mock.patch.object(llm, "complete", side_effect=UserError("ai_error", "The AI service returned an error (401).")):
            r = assistant.ask(self.uid, self.demo, "what does pop do", "video", 150, [])
        self.assertEqual((r["status"], r["mode"]), ("ok", "demo"))
        self.assertIn("demo-mode", r["warning"])

    def test_daily_budget_is_enforced(self):
        m = self.live("Pop [1].")
        with mock.patch.object(config, "DAILY_AI_CALLS", 2):
            modes = [assistant.ask(self.uid, self.demo, "what does pop do", "video", 150, [])["mode"] for _ in range(4)]
        self.assertEqual(modes, ["live", "live", "demo", "demo"])
        self.assertEqual(m.call_count, 2)

    def test_no_evidence_does_not_cost_an_ai_call(self):
        m = self.live()
        assistant.ask(self.uid, self.demo, "what is a dictionary", "video", 150, [])
        m.assert_not_called()


class StudyTests(Base):
    def test_summary_and_notes_only_use_watched_part(self):
        r = assistant.study(self.uid, self.demo, "notes", "video", 40, None, None)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(all(s["time"] <= 40 for s in r["sources"]))
        self.assertNotIn("append", r["answer"].lower())

    def test_nothing_to_summarize_for_documents(self):
        self.assertEqual(assistant.study(self.uid, self.demo, "summary", "docs", None, None, None)["status"], "not_found")

    def test_compare_reports_missing_evidence(self):
        r = assistant.study(self.uid, self.demo, "compare", "video", 240, "append", "zebra")
        self.assertEqual(r["status"], "ok")
        self.assertIn("zebra", r["warning"])

    def test_compare_needs_two_concepts(self):
        with self.assertRaises(UserError):
            assistant.study(self.uid, self.demo, "compare", "video", 240, "append", "")


class QuizTests(Base):
    def test_demo_quiz_is_valid_gated_and_gradable(self):
        r = assistant.make_quiz(self.uid, self.demo, "video", 70, 4)
        self.assertEqual(r["status"], "ok")
        for q in r["questions"]:
            self.assertEqual(len(q["options"]), 4)
            self.assertNotIn("answer", q)                    # answers are not sent to the browser
        saved = store.load_obj(self.uid, "quizzes", r["quiz_id"])
        self.assertTrue(all(q["source"]["time"] <= 70 for q in saved["questions"]))
        perfect = [q["answer"] for q in saved["questions"]]
        g = assistant.grade_quiz(self.uid, r["quiz_id"], perfect)
        self.assertEqual((g["score"], g["total"]), (len(perfect), len(perfect)))
        g2 = assistant.grade_quiz(self.uid, r["quiz_id"], [None] * len(perfect))
        self.assertEqual(g2["score"], 0)
        self.assertEqual(len(store.get_progress(self.uid)[DEMO]["quizzes"]), 2)

    def test_live_quiz_drops_questions_with_invented_source(self):
        good = {"q": "Q?", "options": ["a", "b", "c", "d"], "answer": 1, "explanation": "e", "source": 1}
        bad = dict(good, source=99)
        self.live(json.dumps({"questions": [good, bad, {"q": "no options"}]}))
        r = assistant.make_quiz(self.uid, self.demo, "video", 100, 5)
        self.assertEqual(len(r["questions"]), 1)

    def test_unusable_ai_quiz_falls_back_to_offline(self):
        self.live("sorry, I cannot do JSON")
        r = assistant.make_quiz(self.uid, self.demo, "video", 200, 3)
        self.assertEqual((r["status"], r["mode"]), ("ok", "demo"))

    def test_wrong_number_of_answers_is_rejected(self):
        r = assistant.make_quiz(self.uid, self.demo, "video", 200, 3)
        with self.assertRaises(UserError):
            assistant.grade_quiz(self.uid, r["quiz_id"], [0])


if __name__ == "__main__":
    unittest.main()
