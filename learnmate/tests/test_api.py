import io
import json
import unittest
from unittest import mock

from helpers import Base, config, H, DEMO
import interview
import store
from app import create_app

TXT = ("Photosynthesis happens in the chloroplast of plant cells.\n"
       "Chlorophyll absorbs light energy and starts the process.\n"
       "Plants turn carbon dioxide and water into glucose and oxygen.\n")
SRT = b"1\n00:00:00,000 --> 00:00:20,000\nWelcome to the lesson about tides.\n\n2\n00:00:20,000 --> 00:00:40,000\nThe moon pulls on the ocean and creates tides.\n"


class ApiBase(Base):
    def setUp(self):
        super().setUp()
        self.app = create_app()
        self.c = self.app.test_client()

    def post(self, url, data=None, client=None, **kw):
        return (client or self.c).post(url, json=data, headers=H, **kw)

    def upload(self, name, data, client=None, cid=None):
        return (client or self.c).post(f"/api/courses/{cid}/documents", data={"file": (io.BytesIO(data), name)},
                                       headers=H, content_type="multipart/form-data")

    def new_course(self, client=None, **extra):
        fields = {"title": "My course", **extra}
        return (client or self.c).post("/api/courses", data=fields, headers=H, content_type="multipart/form-data")


class CoreApiTests(ApiBase):
    def test_pages_and_health(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/api/health").get_json(), {"status": "ok"})
        r = self.c.get("/")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])

    def test_demo_course_is_listed_and_video_streams_with_ranges(self):
        ids = [c["id"] for c in self.c.get("/api/courses").get_json()["courses"]]
        self.assertEqual(ids, [DEMO])
        r = self.c.get("/media/demo.mp4", headers={"Range": "bytes=0-99"})
        self.assertEqual((r.status_code, len(r.data)), (206, 100))

    def test_requests_without_the_header_are_blocked(self):
        r = self.c.post("/api/ask", json={})
        self.assertEqual(r.status_code, 403)
        self.assertIn("message", r.get_json()["error"])

    def test_ask_is_gated_by_time(self):
        q = {"course_id": DEMO, "scope": "video", "question": "how do I add an item to a list"}
        early = self.post("/api/ask", {**q, "current_time": 40}).get_json()
        late = self.post("/api/ask", {**q, "current_time": 100}).get_json()
        self.assertEqual(early["status"], "not_found")
        self.assertEqual(late["status"], "ok")
        self.assertTrue(all(s["time"] <= 100 for s in late["sources"]))

    def test_friendly_errors(self):
        r = self.post("/api/ask", {"course_id": DEMO, "scope": "video", "question": "hi", "current_time": "abc"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("number", r.get_json()["error"]["message"])
        self.assertEqual(self.post("/api/ask", {"course_id": "nope", "question": "hi"}).status_code, 404)
        self.assertEqual(self.c.get("/api/nothing").status_code, 404)
        self.assertEqual(self.c.put("/api/ask", headers=H).status_code, 405)

    def test_secret_key_never_leaves_the_server(self):
        with mock.patch.object(config, "LLM_API_KEY", "sk-VERY-SECRET"):
            for url in ("/api/config", "/api/courses", "/api/progress", "/"):
                self.assertNotIn(b"sk-VERY-SECRET", self.c.get(url).data)

    def test_rate_limit(self):
        with mock.patch.object(config, "RATE_PER_MIN", 3):
            codes = [self.post("/api/ask", {"course_id": DEMO, "question": "x", "scope": "docs"}).status_code for _ in range(5)]
        self.assertEqual(codes[-1], 429)

    def test_progress_tracking(self):
        self.post("/api/progress/watch", {"course_id": DEMO, "position": 120})
        self.post("/api/progress/watch", {"course_id": DEMO, "position": 60})      # going back does not lower progress
        self.post("/api/ask", {"course_id": DEMO, "scope": "video", "question": "what does pop do", "current_time": 150})
        c = self.c.get("/api/courses/" + DEMO).get_json()["progress"]
        self.assertEqual((c["max_position"], c["percent_watched"], c["questions"]), (120, 50, 1))

    def test_demo_course_is_read_only(self):
        self.assertEqual(self.c.delete("/api/courses/" + DEMO, headers=H).status_code, 403)
        self.assertEqual(self.upload("a.txt", b"hello there friend", cid=DEMO).status_code, 403)


class UploadAndIsolationTests(ApiBase):
    def test_upload_ask_and_cite_exact_lines(self):
        cid = self.new_course().get_json()["id"]
        r = self.upload("biology.txt", TXT.encode(), cid=cid)
        self.assertEqual(r.status_code, 201)
        a = self.post("/api/ask", {"course_id": cid, "scope": "docs", "question": "where does photosynthesis happen"}).get_json()
        self.assertEqual(a["status"], "ok")
        self.assertEqual(a["sources"][0]["label"], "biology.txt lines 1-4")
        self.assertIn("chloroplast", a["sources"][0]["snippet"])
        nf = self.post("/api/ask", {"course_id": cid, "scope": "docs", "question": "who won the football match"}).get_json()
        self.assertEqual(nf["status"], "not_found")
        r = self.post("/api/ask", {"course_id": cid, "scope": "video", "question": "x", "current_time": 5})
        self.assertEqual(r.get_json()["error"]["code"], "no_video")

    def test_bad_uploads_are_rejected_with_hints(self):
        cid = self.new_course().get_json()["id"]
        for name, data, status in (("evil.exe", b"MZ", 415), ("fake.pdf", b"hello", 400), ("empty.txt", b"", 400)):
            r = self.upload(name, data, cid=cid)
            self.assertEqual(r.status_code, status, name)
            self.assertTrue(r.get_json()["error"]["message"])
        self.assertEqual(self.c.get("/api/courses/" + cid).get_json()["documents"], [])

    def test_oversized_request_is_413(self):
        cid = self.new_course().get_json()["id"]
        self.app.config["MAX_CONTENT_LENGTH"] = 1000          # the web server refuses huge bodies before reading them
        r = self.upload("a.txt", b"x" * 5000, cid=cid)
        self.assertEqual(r.status_code, 413)
        self.assertIn("MB", r.get_json()["error"]["message"])

    def test_document_limit_and_delete(self):
        cid = self.new_course().get_json()["id"]
        with mock.patch.object(config, "MAX_DOCS_PER_COURSE", 1):
            first = self.upload("a.txt", TXT.encode(), cid=cid).get_json()
            self.assertEqual(self.upload("b.txt", TXT.encode(), cid=cid).status_code, 403)
        did = first["documents"][0]["id"]
        r = self.c.delete(f"/api/courses/{cid}/documents/{did}", headers=H).get_json()
        self.assertEqual(r["documents"], [])

    def test_users_cannot_see_each_others_courses_or_files(self):
        alice, bob = self.app.test_client(), self.app.test_client()
        cid = self.new_course(client=alice).get_json()["id"]
        self.upload("secret.txt", TXT.encode(), client=alice, cid=cid)
        self.assertEqual([c["id"] for c in bob.get("/api/courses").get_json()["courses"]], [DEMO])
        self.assertEqual(bob.get("/api/courses/" + cid).status_code, 404)
        self.assertEqual(self.post("/api/ask", {"course_id": cid, "scope": "docs", "question": "photosynthesis"}, client=bob).status_code, 404)
        self.assertEqual(bob.delete("/api/courses/" + cid, headers=H).status_code, 404)
        self.assertEqual(len(alice.get("/api/courses").get_json()["courses"]), 2)

    def test_path_tricks_are_blocked(self):
        for bad in ("../x" * 8, "a/b" * 8, ""):
            with self.assertRaises(Exception):
                store.get_course(bad, "abcdef123456")
        self.assertEqual(self.c.get("/api/courses/..%2F..%2Fetc").status_code, 404)

    def test_course_with_video_url_and_transcript(self):
        r = self.new_course(video_url="https://example.com/tides.mp4", transcript=(io.BytesIO(SRT), "tides.srt"))
        self.assertEqual(r.status_code, 201)
        cid = r.get_json()["id"]
        a = self.post("/api/ask", {"course_id": cid, "scope": "video", "question": "what creates tides", "current_time": 30}).get_json()
        self.assertEqual(a["status"], "ok")
        early = self.post("/api/ask", {"course_id": cid, "scope": "video", "question": "what creates tides", "current_time": 10}).get_json()
        self.assertEqual(early["status"], "not_found")                                   # the moon sentence starts at 20 s

    def test_course_validation(self):
        # A video can now be created with or without transcript
        res = self.new_course(video_url="https://example.com/a.mp4")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.new_course(video_url="javascript:alert(1)", transcript=(io.BytesIO(SRT), "t.srt")).get_json()["error"]["code"], "bad_url")
        self.assertEqual(self.c.post("/api/courses", data={"title": ""}, headers=H, content_type="multipart/form-data").status_code, 400)
        with mock.patch.object(config, "MAX_COURSES_PER_USER", 1):
            self.new_course()
            self.assertEqual(self.new_course().status_code, 403)


class InterviewTests(ApiBase):
    def start(self, cid=DEMO):
        return self.post("/api/interview/start", {"course_id": cid, "count": 3}).get_json()

    def answer(self, iid, text):
        return self.post(f"/api/interview/{iid}/answer", {"answer": text})

    def test_scoring_is_rule_based_and_explainable(self):
        q = {"key_points": [{"name": "square brackets", "terms": ["bracket", "["]}, {"name": "commas", "terms": ["comma"]}]}
        self.assertEqual(interview.score_answer(q, "You write them in [square brackets]"), (["square brackets"], ["commas"]))
        self.assertEqual(interview.score_answer(q, "brackets and commas"), (["square brackets", "commas"], []))

    def test_weak_answer_gets_a_follow_up_then_next_question(self):
        d = self.start()
        first = d["question"]
        r = self.answer(d["interview_id"], "I do not know").get_json()
        self.assertTrue(r["is_follow_up"])
        self.assertIn("did not mention", r["question"])
        r2 = self.answer(d["interview_id"], "still not sure").get_json()
        self.assertFalse(r2.get("is_follow_up", False))
        self.assertNotEqual(r2["question"], first)

    UNIVERSAL = ("append insert square brackets [] comma zero index position value returns negative -1 end included "
                 "excluded new list one line for loop expression")

    def test_strong_answer_makes_the_next_question_harder(self):
        d = self.start()
        self.assertEqual(d["level"], "easy")
        r = self.answer(d["interview_id"], self.UNIVERSAL).get_json()
        self.assertEqual(r["level"], "hard")                                  # adapted upward
        self.assertIn("harder", r["note"])

    def test_full_interview_scorecard(self):
        d = self.start()
        iid = d["interview_id"]
        r = d
        guard = 0
        while not r.get("finished") and guard < 12:
            r = self.answer(iid, self.UNIVERSAL).get_json()
            guard += 1
        self.assertTrue(r["finished"])
        card = self.c.get(f"/api/interview/{iid}/scorecard").get_json()
        self.assertEqual(len(card["questions"]), 3)
        for q in card["questions"]:
            self.assertEqual(set(q), {"question", "level", "score_percent", "covered", "missed", "follow_up_on", "answer_words"})
        self.assertIn("how_scored", card)
        self.assertEqual(self.c.get(f"/api/progress").get_json()["courses"][0]["progress"]["interviews"], [card["overall_percent"]])

    def test_errors(self):
        d = self.start()
        iid = d["interview_id"]
        self.assertEqual(self.answer(iid, "").status_code, 400)
        self.assertEqual(self.c.get(f"/api/interview/{iid}/scorecard").get_json()["error"]["code"], "not_finished")
        self.assertEqual(self.answer("abcdefabcdef", "hello there").status_code, 404)

    def test_other_users_cannot_use_my_interview(self):
        d = self.start()
        other = self.app.test_client()
        r = self.post(f"/api/interview/{d['interview_id']}/answer", {"answer": "hello there"}, client=other)
        self.assertEqual(r.status_code, 404)

    def test_user_course_interview_works_offline(self):
        cid = self.new_course().get_json()["id"]
        self.upload("bio.txt", "\n".join(f"Sentence {i} explains cell biology topic number {i} with enough words inside." for i in range(60)).encode(), cid=cid)
        d = self.start(cid)
        self.assertIn("question", d)
        self.assertEqual(d["mode"], "demo")

    def test_not_enough_content(self):
        cid = self.new_course().get_json()["id"]
        r = self.post("/api/interview/start", {"course_id": cid})
        self.assertEqual(r.get_json()["error"]["code"], "not_enough_content")


class ApiKeyAndVideoTests(ApiBase):
    def test_api_key_endpoints(self):
        cfg1 = self.c.get("/api/config").get_json()
        self.assertFalse(cfg1["has_user_key"])

        res = self.post("/api/config/key", {"api_key": "AIzaSyTestKey123"})
        self.assertTrue(res.get_json()["has_key"])

        cfg2 = self.c.get("/api/config").get_json()
        self.assertTrue(cfg2["has_user_key"])
        self.assertEqual(cfg2["mode"], "live")

        del_res = self.c.delete("/api/config/key", headers=H)
        self.assertFalse(del_res.get_json()["has_key"])

    def test_youtube_url_parsing(self):
        urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://example.com/video.mp4", "direct")
        ]
        for url, expected_type in urls:
            r = self.new_course(video_url=url, title=f"Course for {expected_type}")
            c = r.get_json()
            self.assertEqual(c["video_type"], expected_type)

    def test_youtube_auto_transcript(self):
        fake_cues = [{"start": 0.0, "end": 10.0, "text": "Automatic transcript hello"}]
        with mock.patch("ingest.fetch_youtube_transcript", return_value=fake_cues):
            r = self.new_course(video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Auto Sub Course")
            c = r.get_json()
            self.assertEqual(c["video_type"], "youtube")
            self.assertEqual(c["duration"], 10.0)

    def test_interview_passes_session_credentials(self):
        self.post("/api/config/key", {"api_key": "custom-key", "base_url": "https://custom.api/v1", "model": "custom-model"})
        fake_qs = json.dumps({"questions": [
            {"question": "Q1?", "level": "easy", "key_points": [{"name": "kp1", "terms": ["t1", "t2"]}]},
            {"question": "Q2?", "level": "hard", "key_points": [{"name": "kp2", "terms": ["t3", "t4"]}]}
        ]})
        with mock.patch("llm.complete", return_value=fake_qs) as m:
            r = self.post("/api/interview/start", {"course_id": DEMO, "count": 2})
            self.assertEqual(r.status_code, 200)


    def test_youtube_time_gating_never_leaks_future_content(self):
        fake_cues = [
            {"start": 0.0, "end": 20.0, "text": "Topic one about introductory principles"},
            {"start": 30.0, "end": 60.0, "text": "Topic two introducing quantum physics calculations"}
        ]
        with mock.patch("ingest.fetch_youtube_transcript", return_value=fake_cues):
            r = self.new_course(video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Physics Lecture")
            cid = r.get_json()["id"]

        # At timestamp 15s (before 30s), quantum physics must NOT be accessible
        early_res = self.post("/api/ask", {"course_id": cid, "scope": "video", "question": "what is quantum physics", "current_time": 15}).get_json()
        self.assertEqual(early_res["status"], "not_found")

        # At timestamp 45s, quantum physics must be accessible
        late_res = self.post("/api/ask", {"course_id": cid, "scope": "video", "question": "what is quantum physics", "current_time": 45}).get_json()
        self.assertEqual(late_res["status"], "ok")
        self.assertTrue(all(s["time"] <= 45 for s in late_res["sources"]))

    def test_docx_paragraph_and_run_extraction(self):
        import zipfile
        buf = io.BytesIO()
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Distributed </w:t></w:r><w:r><w:t>consensus protocols</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Raft and Paxos ensure consistency.</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        
        cid = self.new_course().get_json()["id"]
        res = self.upload("distributed.docx", buf.getvalue(), cid=cid)
        self.assertEqual(res.status_code, 201)
        docs = res.get_json()["documents"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "distributed.docx")

    def test_secret_key_rejection_of_weak_defaults(self):
        with mock.patch.dict("os.environ", {"SECRET_KEY": "change-me"}):
            import importlib
            import config as cfg
            # When weak, config must substitute a high-entropy 64-char hex key
            _raw = cfg.os.getenv("SECRET_KEY", "").strip()
            self.assertEqual(_raw, "change-me")
            self.assertNotEqual(cfg.SECRET_KEY, "change-me")
    def test_lms_launch_and_grade_export(self):
        # 1. Test LMS launch simulation
        res = self.post("/api/lms/launch", {"lms_user_id": "canvas_student_42", "lms_course_id": "cs101_fall", "role": "learner"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["lms_user_id"], "canvas_student_42")

        # 2. Test LMS gradebook export
        exp = self.c.get(f"/api/lms/export/{DEMO}").get_json()
        self.assertEqual(exp["course_id"], DEMO)
        self.assertEqual(exp["lms_user_id"], "canvas_student_42")
        self.assertIn("watched_seconds", exp)
        self.assertIn("synced_at", exp)


if __name__ == "__main__":
    unittest.main()
