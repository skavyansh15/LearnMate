# API

All endpoints are JSON under `/api`. Every non-GET request must send the header `X-Requested-With: fetch` (simple CSRF protection). A cookie created on first visit identifies the anonymous user. Errors always look like:

```json
{"error": {"code": "bad_pdf", "message": "This file is not a real PDF.", "hint": "Export it again as PDF."}}
```

Answer objects: `{"status": "ok" | "not_found", "answer": "...[1]", "sources": [{"n":1,"type":"video|pdf|slide|txt","label":"notes.pdf p.2","time":120.0|null,"snippet":"..."}], "mode":"demo|live", "warning":"(optional)"}`

| Method + path | Body | Returns |
|---|---|---|
| `GET /api/health` | - | `{"status":"ok"}` |
| `GET /api/config` | - | mode (`demo`/`live`), model, AI calls used today / limit. **Never the key.** |
| `GET /api/courses` | - | all courses (demo + yours) with progress |
| `GET /api/courses/<id>` | - | one course summary |
| `POST /api/courses` | multipart: `title`, `video_url` (opt.), `transcript` (.srt/.vtt, required with a video) | `201` course |
| `DELETE /api/courses/<id>` | - | `{"deleted": id}` (demo: `403`) |
| `POST /api/courses/<id>/documents` | multipart: `file` (.pdf/.pptx/.txt, <= 10 MB) | `201` course with `documents` |
| `DELETE /api/courses/<id>/documents/<doc_id>` | - | course |
| `POST /api/ask` | `{course_id, question, scope: "video"\|"docs", current_time, history:[{role,content}]}` | answer object |
| `POST /api/study` | `{course_id, kind: "summary"\|"notes"\|"compare", scope, current_time, a, b}` | answer object |
| `POST /api/quiz` | `{course_id, scope, current_time, count}` | `{status, quiz_id, questions:[{q, options[4]}], mode}` |
| `POST /api/quiz/<id>/grade` | `{answers:[index\|null,...]}` | `{score, total, results:[{correct, answer, explanation, source}]}` |
| `POST /api/progress/watch` | `{course_id, position}` | `{ok:true}` (keeps the furthest position) |
| `GET /api/progress` | - | courses with progress |
| `POST /api/interview/start` | `{course_id, count: 2-6}` | `{interview_id, question, level, number, total, note, mode}` |
| `POST /api/interview/<id>/answer` | `{answer}` | next question (`is_follow_up` true on follow-ups) or `{finished:true}` |
| `GET /api/interview/<id>/scorecard` | - | overall %, level, per-question covered/missed, strengths, gaps, `how_scored` |
| `POST /api/lms/launch` | `{lms_user_id, lms_course_id, role}` | `{status, lms_user_id, lms_course_id, role, courses_available}` |
| `GET /api/lms/export/<cid>` | - | `{course_id, watched_seconds, quizzes_completed, quiz_average_percent, interviews_completed, interview_scores, synced_at}` |

`scope: "video"` needs `current_time` (seconds) and only sees content unlocked up to it. `scope: "docs"` only sees your uploaded documents. YouTube transcripts are extracted automatically when not uploaded manually.

Common status codes: `400` bad input, `403` blocked (CSRF, read-only demo, quota), `404` not found (also for other users' items), `413` too big, `415` wrong file type, `429` too many requests, `502` AI service problem (the app then falls back to demo answers where possible).
