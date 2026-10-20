import logging
import re
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

import assistant
import config
import ingest
import interview
import llm
import store
from errors import UserError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("learnmate")


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config.update(SECRET_KEY=config.SECRET_KEY, MAX_CONTENT_LENGTH=(config.MAX_UPLOAD_MB + 2) * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=config.COOKIE_SECURE, PERMANENT_SESSION_LIFETIME=90 * 86400)

    # ---------- every request ---------------------------------------------------
    @app.before_request
    def guard():
        if not request.path.startswith("/api/"):
            return
        if "uid" not in session:
            session["uid"] = store.new_uid()  # anonymous per-browser user
        session.permanent = True
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Requested-With") != "fetch":
            raise UserError("csrf", "Request blocked.", "Use the LearnMate web page.", 403)  # simple CSRF protection
        if request.method == "POST" and not store.rate_ok(session["uid"]):
            raise UserError("rate_limit", "You are going a bit fast.", "Wait a minute and try again.", 429)

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Content-Security-Policy"] = ("default-src 'self' https: data: blob:; "
                                                   "script-src 'self' 'unsafe-inline' https://www.youtube.com https://s.ytimg.com; "
                                                   "style-src 'self' 'unsafe-inline'; "
                                                   "media-src * blob: data:; img-src * data:; "
                                                   "frame-src https://www.youtube.com https://www.youtube-nocookie.com https://player.vimeo.com *; "
                                                   "frame-ancestors 'none'; base-uri 'none'")
        return resp

    def parse_video_info(url):
        if not url:
            return None, None
        url = url.strip()
        yt_id = ingest.extract_youtube_id(url)
        if yt_id:
            return "youtube", f"https://www.youtube.com/embed/{yt_id}"
        return "direct", url

    @app.errorhandler(UserError)
    def user_error(e):
        return jsonify(error={"code": e.code, "message": e.message, "hint": e.hint}), e.status

    @app.errorhandler(413)
    def too_big(_):
        return jsonify(error={"code": "too_big", "message": f"Upload is larger than {config.MAX_UPLOAD_MB} MB.",
                              "hint": "Use a smaller file."}), 413

    @app.errorhandler(404)
    def missing(_):
        return jsonify(error={"code": "not_found", "message": "Not found.", "hint": ""}), 404

    @app.errorhandler(Exception)
    def crash(e):
        if isinstance(e, HTTPException):  # e.g. 405 Method Not Allowed
            return jsonify(error={"code": "http_error", "message": e.name, "hint": ""}), e.code
        app.logger.exception("Unhandled error")
        return jsonify(error={"code": "server_error", "message": "Something went wrong on our side.",
                              "hint": "Try again. If it keeps happening, check the server log."}), 500

    uid = lambda: session["uid"]

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def number(value, name, required=False):
        if value is None and not required:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise UserError("bad_request", f"'{name}' must be a number.")

    def editable(cid):
        if store.is_demo(cid):
            raise UserError("read_only", "The demo course cannot be changed.", "Create your own course instead.", 403)
        return store.get_course(uid(), cid)

    # ---------- basic ---------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/media/demo.mp4")
    def demo_video():
        return send_from_directory(config.DEMO_DIR, "lecture.mp4", conditional=True)  # supports seeking

    @app.get("/media/demo/<filename>")
    def demo_file(filename):
        safe_files = {"lecture_notes.pdf", "lecture_slides.pptx", "lecture.srt", "lecture.mp4"}
        if filename not in safe_files:
            raise UserError("not_found", "File not found.", status=404)
        return send_from_directory(config.DEMO_DIR, filename, conditional=True)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config():
        # NEVER include the API key itself here
        user_key = session.get("api_key")
        live = llm.is_live(user_key)
        model = session.get("model") or config.LLM_MODEL
        base_url = session.get("base_url") or config.LLM_BASE_URL
        return {"mode": "live" if live else "demo", "model": model if live else None,
                "base_url": base_url if live else None,
                "ai_calls_today": store.usage_today(uid()), "ai_calls_limit": config.DAILY_AI_CALLS,
                "max_upload_mb": config.MAX_UPLOAD_MB, "has_user_key": bool(user_key)}

    @app.post("/api/config/key")
    def set_api_key():
        d = body()
        key = (d.get("api_key") or "").strip()
        model = (d.get("model") or "").strip()
        base_url = (d.get("base_url") or "").strip()
        if not key:
            session.pop("api_key", None)
            session.pop("model", None)
            session.pop("base_url", None)
            return {"ok": True, "has_key": False}
        session["api_key"] = key
        if model:
            session["model"] = model
        if base_url:
            session["base_url"] = base_url
        return {"ok": True, "has_key": True}

    @app.delete("/api/config/key")
    def clear_api_key():
        session.pop("api_key", None)
        session.pop("model", None)
        session.pop("base_url", None)
        return {"ok": True, "has_key": False}

    # ---------- courses -------------------------------------------------------
    def summary(c):
        prog = store.get_progress(uid()).get(c["id"], {})
        duration = c["cues"][-1]["end"] if c.get("cues") else 0
        docs = []
        for d in c.get("documents", []):
            d_item = dict(d)
            if store.is_demo(c["id"]):
                d_item["url"] = f"/media/demo/{d['name']}"
            else:
                d_item["url"] = f"/api/courses/{c['id']}/documents/{d['id']}/download"
            docs.append(d_item)
        return {"id": c["id"], "title": c["title"], "demo": store.is_demo(c["id"]), "has_video": c.get("has_video", False),
                "video_url": c.get("video_url"), "video_type": c.get("video_type", "direct"),
                "video_embed": c.get("video_embed"), "duration": duration, "documents": docs,
                "progress": {"max_position": prog.get("max_position", 0), "questions": prog.get("questions", 0),
                             "quizzes": prog.get("quizzes", []), "interviews": prog.get("interviews", []),
                             "percent_watched": round(100 * min(prog.get("max_position", 0) / duration, 1)) if duration else 0}}

    @app.get("/api/courses")
    def courses():
        return {"courses": [summary(c) for c in store.list_courses(uid())]}

    @app.get("/api/courses/<cid>")
    def course(cid):
        return summary(store.get_course(uid(), cid))

    @app.get("/api/courses/<cid>/video")
    def stream_course_video(cid):
        c = store.get_course(uid(), cid)
        local_filename = c.get("local_video")
        if not local_filename:
            raise UserError("not_found", "No local video found for this course.", status=404)
        vdir = store.course_dir(uid(), cid)
        return send_from_directory(vdir, local_filename, conditional=True)

    @app.post("/api/courses")
    def create_course():
        if store.count_courses(uid()) >= config.MAX_COURSES_PER_USER:
            raise UserError("quota", f"You can have at most {config.MAX_COURSES_PER_USER} courses.", "Delete one first.", 403)
        title = (request.form.get("title") or "").strip()
        if not 1 <= len(title) <= 80:
            raise UserError("bad_title", "Give the course a title (max 80 characters).")
        url = (request.form.get("video_url") or "").strip()
        vfile = request.files.get("video_file")
        f = request.files.get("transcript")
        cues, chunks = [], []
        cid = store.new_id()
        video_type = "none"
        video_url = None
        video_embed = None
        local_video = None

        if vfile and vfile.filename:
            vext = ingest._ext(vfile.filename)
            if vext not in ingest.VIDEO_EXT:
                raise UserError("bad_video_type", f"Unsupported video type '{vext}'. Use .mp4, .webm, or .mkv", status=415)
            vdir = store.course_dir(uid(), cid)
            local_filename = f"video{vext}"
            vpath = vdir / local_filename
            vfile.save(vpath)
            local_video = local_filename
            video_type = "local"
            video_url = f"/api/courses/{cid}/video"
        elif url:
            vtype, target = parse_video_info(url)
            if vtype == "youtube":
                video_type = "youtube"
                video_embed = target
                video_url = url
            else:
                if not re.fullmatch(r"https?://[^\s]{3,480}", url):
                    raise UserError("bad_url", "The video link must start with http:// or https://.")
                video_type = "direct"
                video_url = url

        # Process transcript if provided, or fetch automatically for YouTube
        if f and f.filename:
            if ingest._ext(f.filename) not in ingest.SUB_EXT:
                raise UserError("bad_type", "Transcripts must be .srt or .vtt files.", status=415)
            raw = f.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise UserError("too_big", "Transcript is larger than 2 MB.", status=413)
            try:
                cues = ingest.parse_subtitles(raw.decode("utf-8-sig"))
            except UnicodeDecodeError:
                raise UserError("bad_transcript", "The transcript is not UTF-8 text.", "Save it as UTF-8.")
            chunks = ingest.chunk_cues(cues)
            for i, c in enumerate(chunks):
                c["id"] = f"v{i}"
        elif video_type == "youtube" and video_embed:
            # Automatically fetch YouTube captions
            try:
                auto_cues = ingest.fetch_youtube_transcript(video_embed)
                if auto_cues:
                    cues = auto_cues
                    chunks = ingest.chunk_cues(cues)
                    for i, c in enumerate(chunks):
                        c["id"] = f"v{i}"
            except Exception:
                pass

        has_video = bool(video_type != "none")
        c = {"id": cid, "title": title, "created": time.time(), "has_video": has_video,
             "video_type": video_type, "video_url": video_url, "video_embed": video_embed,
             "local_video": local_video, "cues": cues, "chunks": chunks, "documents": []}
        store.save_course(uid(), c)
        return summary(c), 201

    @app.delete("/api/courses/<cid>")
    def delete_course(cid):
        editable(cid)
        store.delete_course(uid(), cid)
        return {"deleted": cid}

    @app.post("/api/courses/<cid>/documents")
    def add_document(cid):
        c = editable(cid)
        f = request.files.get("file")
        if not f or not f.filename:
            raise UserError("no_file", "Choose a file first.")
        if len(c["documents"]) >= config.MAX_DOCS_PER_COURSE:
            raise UserError("quota", f"A course can have at most {config.MAX_DOCS_PER_COURSE} documents.", "Delete one first.", 403)
        name = Path(f.filename).name[:80]  # drop any path parts
        raw_bytes = f.read()
        kind, chunks, pages = ingest.extract_document(name, raw_bytes)
        did = store.new_id()
        for i, ch in enumerate(chunks):
            ch["id"], ch["doc_id"] = f"{did}-{i}", did
        c["chunks"] += chunks
        # Save raw file so user can download/open it anytime
        mdir = store.course_dir(uid(), cid)
        ext = ingest._ext(name)
        saved_name = f"doc_{did}{ext}"
        try:
            (mdir / saved_name).write_bytes(raw_bytes)
        except Exception:
            saved_name = None
        c["documents"].append({"id": did, "name": name, "kind": kind, "pages": pages, "file": saved_name})
        store.save_course(uid(), c)
        return summary(c), 201

    @app.delete("/api/courses/<cid>/documents/<did>")
    def delete_document(cid, did):
        c = editable(cid)
        target = next((d for d in c["documents"] if d["id"] == did), None)
        if target and target.get("file"):
            try:
                (store.course_dir(uid(), cid) / target["file"]).unlink(missing_ok=True)
            except Exception:
                pass
        c["documents"] = [d for d in c["documents"] if d["id"] != did]
        c["chunks"] = [ch for ch in c["chunks"] if ch.get("doc_id") != did]
        store.save_course(uid(), c)
        return summary(c)

    @app.get("/api/courses/<cid>/documents/<did>/download")
    def download_document(cid, did):
        c = store.get_course(uid(), cid)
        if store.is_demo(cid):
            doc = next((d for d in c.get("documents", []) if d["id"] == did), None)
            if not doc:
                raise UserError("not_found", "Document not found.", status=404)
            return send_from_directory(config.DEMO_DIR, doc["name"], conditional=True)
        doc = next((d for d in c.get("documents", []) if d["id"] == did), None)
        if not doc:
            raise UserError("not_found", "Document not found.", status=404)
        vdir = store.course_dir(uid(), cid)
        filename = doc.get("file") or doc.get("name")
        return send_from_directory(vdir, filename, download_name=doc["name"], conditional=True)

    # ---------- learning assistant ---------------------------------------------
    @app.post("/api/ask")
    def ask():
        d = body()
        c = store.get_course(uid(), str(d.get("course_id", "")))
        t = number(d.get("current_time"), "current_time", required=d.get("scope") == "video")
        history = [{"role": m.get("role"), "content": str(m.get("content", ""))[:2000]}
                   for m in d.get("history", [])[-4:] if isinstance(m, dict)] if isinstance(d.get("history"), list) else []
        res = assistant.ask(uid(), c, d.get("question"), d.get("scope", "video"), t, history,
                            api_key=session.get("api_key"), base_url=session.get("base_url"), model=session.get("model"))
        if res["status"] != "error":
            store.update_progress(uid(), c["id"], lambda r: r.update(questions=r["questions"] + 1))
        return res

    @app.post("/api/study")
    def study():
        d = body()
        c = store.get_course(uid(), str(d.get("course_id", "")))
        t = number(d.get("current_time"), "current_time", required=d.get("scope") == "video")
        return assistant.study(uid(), c, d.get("kind"), d.get("scope", "video"), t, d.get("a"), d.get("b"),
                               api_key=session.get("api_key"), base_url=session.get("base_url"), model=session.get("model"))

    @app.post("/api/quiz")
    def quiz():
        d = body()
        c = store.get_course(uid(), str(d.get("course_id", "")))
        t = number(d.get("current_time"), "current_time", required=d.get("scope") == "video")
        return assistant.make_quiz(uid(), c, d.get("scope", "video"), t, d.get("count", 5),
                                   api_key=session.get("api_key"), base_url=session.get("base_url"), model=session.get("model"))

    @app.post("/api/quiz/<qid>/grade")
    def grade(qid):
        return assistant.grade_quiz(uid(), qid, body().get("answers"))

    # ---------- progress ---------------------------------------------------------
    @app.post("/api/progress/watch")
    def watch():
        d = body()
        c = store.get_course(uid(), str(d.get("course_id", "")))
        pos = max(0.0, number(d.get("position"), "position", required=True))
        store.update_progress(uid(), c["id"], lambda r: r.update(max_position=max(r["max_position"], pos)))
        return {"ok": True}

    @app.get("/api/progress")
    def progress():
        return {"courses": [summary(c) for c in store.list_courses(uid())]}

    # ---------- mock interview -----------------------------------------------------
    @app.post("/api/interview/start")
    def interview_start():
        d = body()
        return interview.start(uid(), store.get_course(uid(), str(d.get("course_id", ""))), d.get("count", 4),
                               api_key=session.get("api_key"), base_url=session.get("base_url"), model=session.get("model"))

    @app.post("/api/interview/<iid>/answer")
    def interview_answer(iid):
        return interview.answer(uid(), iid, body().get("answer"))

    @app.get("/api/interview/<iid>/scorecard")
    def interview_scorecard(iid):
        return interview.scorecard(uid(), iid, api_key=session.get("api_key"), base_url=session.get("base_url"), model=session.get("model"))

    # ---------- LMS integration (Canvas / Moodle / Blackboard) --------------------
    @app.post("/api/lms/launch")
    def lms_launch():
        """Launch endpoint for external LMS tools (LTI 1.3 / LTI Advantage simulation).
        Accepts learner identity, LMS course id, and optional role."""
        d = body()
        lms_user = str(d.get("lms_user_id") or "").strip()
        lms_course = str(d.get("lms_course_id") or "").strip()
        role = str(d.get("role") or "learner").lower()
        if not lms_user:
            raise UserError("bad_lms_user", "lms_user_id is required for LMS launch.", status=400)
        # Bind LMS user to an isolated session space
        session["lms_user_id"] = lms_user
        session["lms_course_id"] = lms_course
        session["lms_role"] = role
        logger.info(f"LMS_LAUNCH user={lms_user} course={lms_course} role={role}")
        return {
            "status": "connected",
            "lms_user_id": lms_user,
            "lms_course_id": lms_course,
            "role": role,
            "courses_available": [summary(c) for c in store.list_courses(uid())]
        }

    @app.get("/api/lms/export/<cid>")
    def lms_export(cid):
        """Export learner metrics, quiz grades, and interview performance for LMS gradebook sync."""
        c = store.get_course(uid(), cid)
        progress = store.get_progress(uid()).get(cid, {})
        quiz_records = progress.get("quizzes", [])
        avg_quiz = round(100 * sum(q["score"] for q in quiz_records) / sum(q["total"] for q in quiz_records)) if quiz_records else None
        return {
            "course_id": cid,
            "course_title": c["title"],
            "lms_user_id": session.get("lms_user_id", uid()),
            "watched_seconds": progress.get("max_position", 0),
            "quizzes_completed": len(quiz_records),
            "quiz_average_percent": avg_quiz,
            "interviews_completed": len(progress.get("interviews", [])),
            "interview_scores": progress.get("interviews", []),
            "synced_at": time.time()
        }

    return app


app = create_app()

if __name__ == "__main__":
    import os
    mode = "LIVE AI (" + config.LLM_MODEL + ")" if llm.is_live() else "DEMO MODE (no API key needed)"
    print(f"LearnMate AI running in {mode}")
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
