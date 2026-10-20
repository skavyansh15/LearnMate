# API Reference

All application endpoints are served under `/api` and exchange JSON payloads. Non-GET mutations require the header `X-Requested-With: fetch` for CSRF mitigation. Session state is tracked via an encrypted, HTTP-only cookie.

---

## Authentication and Security

- Client requests must provide `X-Requested-With: fetch` on all `POST`, `PUT`, and `DELETE` calls.
- User identity is scoped by a cryptographically signed cookie storing an anonymous user identifier (`uid`).
- Cross-tenant access is prohibited; requests targeting another user's resource identifier return HTTP `404`.

### Error Response Format

All error responses return a structured JSON object with a relevant HTTP status code:

```json
{
  "error": {
    "code": "not_found",
    "message": "Course not found.",
    "hint": "It may have been deleted."
  }
}
```

---

## Endpoint Specification

### System and Configuration

#### GET /api/health
Returns service operational status.

- Response: `200 OK`
  ```json
  {"status": "ok"}
  ```

#### GET /api/config
Returns runtime configuration and remaining per-user quotas. Never exposes raw secret keys.

- Response: `200 OK`
  ```json
  {
    "mode": "live",
    "model": "openai/gpt-oss-20b",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "ai_calls_today": 4,
    "ai_calls_limit": 100,
    "max_upload_mb": 500,
    "has_user_key": false
  }
  ```

---

### Course Management

#### GET /api/courses
Lists all courses accessible to the current session (including the bundled demo course).

- Response: `200 OK`
  ```json
  {
    "courses": [
      {
        "id": "demo-python-lists",
        "title": "Python Lists (demo course)",
        "demo": true,
        "has_video": true,
        "video_url": "/media/demo.mp4",
        "video_type": "direct",
        "duration": 240.0,
        "documents": [
          {
            "id": "d1",
            "name": "lecture_notes.pdf",
            "kind": "pdf",
            "pages": 4,
            "url": "/media/demo/lecture_notes.pdf"
          }
        ],
        "progress": {
          "max_position": 120.0,
          "questions": 3,
          "percent_watched": 50
        }
      }
    ]
  }
  ```

#### GET /api/courses/<course_id>
Retrieves metadata and current progress for a specific course.

- Response: `200 OK`

#### POST /api/courses
Creates a new course module from video links, uploaded video files, or document-only collections.

- Request (multipart/form-data):
  - `title` (string, required): Course title (1 to 80 characters).
  - `video_url` (string, optional): YouTube link or direct video stream URL.
  - `video_file` (file, optional): Local video file (.mp4, .webm, .mkv, .mov).
  - `transcript` (file, optional): Subtitle file (.srt or .vtt). Automatically fetched for YouTube URLs if omitted.
- Response: `201 Created`

#### DELETE /api/courses/<course_id>
Deletes a user-created course and its associated files. Bundled demo courses return `403 Forbidden`.

- Response: `200 OK`
  ```json
  {"deleted": "course_id"}
  ```

---

### Document Management

#### POST /api/courses/<course_id>/documents
Uploads and indexes a syllabus or reference document into the course knowledge base.

- Request (multipart/form-data):
  - `file` (file, required): Document file (.pdf, .pptx, .docx, .txt, .md, .csv).
- Response: `201 Created`

#### DELETE /api/courses/<course_id>/documents/<doc_id>
Removes an indexed document and purges its chunks from retrieval indices.

- Response: `200 OK`

#### GET /api/courses/<course_id>/documents/<doc_id>/download
Downloads or views the source document file.

- Response: `200 OK` with appropriate `Content-Type` header.

#### GET /media/demo/<filename>
Serves static reference materials bundled with the demo course (`lecture_notes.pdf`, `lecture_slides.pptx`, `lecture.srt`, `lecture.mp4`).

- Response: `200 OK` (supports HTTP 206 byte-range seeking for media).

---

### Assistant and Study Tools

#### POST /api/ask
Submits a question to the grounded learning assistant.

- Request:
  ```json
  {
    "course_id": "demo-python-lists",
    "question": "How do negative indexes work?",
    "scope": "video",
    "current_time": 90.0,
    "history": [
      {"role": "user", "content": "What is an index?"},
      {"role": "assistant", "content": "An index is the position of an item..."}
    ]
  }
  ```
- Parameters:
  - `scope` (string): `"video"` gates retrieval to content with `unlock <= current_time`. `"docs"` queries all uploaded course documents without playhead restriction.
  - `current_time` (float): Playhead position in seconds. Required when `scope` is `"video"`.
- Response: `200 OK`
  ```json
  {
    "status": "ok",
    "answer": "Negative indexes count backwards from the end of the list [1]. For example, fruits[-1] returns the last item [2].",
    "sources": [
      {
        "n": 1,
        "type": "video",
        "label": "Video 1:00-1:15",
        "time": 60.0,
        "snippet": "You can also count from the end using negative indexes."
      },
      {
        "n": 2,
        "type": "pdf",
        "label": "lecture_notes.pdf p.1",
        "time": 60.0,
        "snippet": "Negative indexes count from the end: fruits[-1] is cherry."
      }
    ],
    "mode": "live"
  }
  ```

#### POST /api/study
Generates study syntheses based on the unlocked context.

- Request:
  ```json
  {
    "course_id": "demo-python-lists",
    "kind": "summary",
    "scope": "video",
    "current_time": 120.0
  }
  ```
- Kinds:
  - `"summary"`: High-level overview of covered concepts.
  - `"notes"`: Structured revision notes with citations.
  - `"compare"`: Conceptual contrast between parameter `a` and parameter `b`.
- Response: `200 OK`

#### POST /api/quiz
Generates a multiple-choice concept assessment based on covered material.

- Request:
  ```json
  {
    "course_id": "demo-python-lists",
    "scope": "video",
    "current_time": 180.0,
    "count": 5
  }
  ```
- Response: `200 OK`
  ```json
  {
    "status": "ok",
    "quiz_id": "quiz_abc123",
    "questions": [
      {
        "q": "What does fruits.append('mango') do?",
        "options": [
          "Inserts mango at index 0",
          "Adds mango to the end of the list",
          "Replaces the first item with mango",
          "Sorts the list"
        ]
      }
    ],
    "mode": "live"
  }
  ```

#### POST /api/quiz/<quiz_id>/grade
Evaluates submitted quiz answers and returns explanations and evidence citations.

- Request:
  ```json
  {
    "answers": [1, 0, 3, null, 2]
  }
  ```
- Response: `200 OK`
  ```json
  {
    "score": 4,
    "total": 5,
    "results": [
      {
        "correct": true,
        "answer": 1,
        "explanation": "append adds an item to the end of an existing list.",
        "source": {
          "label": "Video 1:30-1:45",
          "time": 90.0,
          "snippet": "To add an item at the end, use the append method."
        }
      }
    ]
  }
  ```

---

### Adaptive Mock Interview

#### POST /api/interview/start
Initializes an adaptive technical interview session based on course content.

- Request:
  ```json
  {
    "course_id": "demo-python-lists",
    "count": 4
  }
  ```
- Response: `200 OK`
  ```json
  {
    "interview_id": "int_789xyz",
    "question": "Explain how list indexing works in Python, including negative indexing.",
    "level": "Core Concept",
    "number": 1,
    "total": 4,
    "note": "Question 1 of 4",
    "mode": "live"
  }
  ```

#### POST /api/interview/<interview_id>/answer
Submits an answer to the current interview question. If conceptual gaps are identified, returns an adaptive follow-up question.

- Request:
  ```json
  {
    "answer": "Indexing starts at zero, so the first item is index 0."
  }
  ```
- Response: `200 OK`
  ```json
  {
    "finished": false,
    "is_follow_up": true,
    "feedback": "You covered basic indexing. Let's explore how negative indexes operate.",
    "question": "What value does an index of -1 return, and how does Python calculate it?",
    "number": 1,
    "total": 4
  }
  ```

#### GET /api/interview/<interview_id>/scorecard
Retrieves the comprehensive rubric evaluation after completing the interview.

- Response: `200 OK`
  ```json
  {
    "overall_percent": 82,
    "level": "Proficient",
    "feedback": "Strong foundational grasp of indexing, slicing, and list operations.",
    "questions": [
      {
        "question": "Explain how list indexing works...",
        "score_percent": 85,
        "covered": ["zero-based counting", "negative indexing", "end access"],
        "missed": ["index bounds error"],
        "follow_up_on": "negative indexing"
      }
    ],
    "strengths": ["Clear syntax explanation", "Good method recall"],
    "gaps": ["Edge-case handling"],
    "how_scored": "Answers are evaluated against concept keywords and required explanation criteria."
  }
  ```

---

### Learning Management System (LMS) Integration

#### POST /api/lms/launch
Accepts an LTI 1.3 learner launch payload, isolating student sessions by university context.

- Request:
  ```json
  {
    "lms_user_id": "canvas_student_4021",
    "lms_course_id": "cs101_fall_2026",
    "role": "learner"
  }
  ```
- Response: `200 OK`
  ```json
  {
    "status": "connected",
    "lms_user_id": "canvas_student_4021",
    "lms_course_id": "cs101_fall_2026",
    "role": "learner",
    "courses_available": 1
  }
  ```

#### GET /api/lms/export/<course_id>
Exports gradebook progress metrics formatted for LMS Assignment and Grade Services (AGS) synchronization.

- Response: `200 OK`
  ```json
  {
    "course_id": "demo-python-lists",
    "lms_user_id": "canvas_student_4021",
    "watched_seconds": 180.0,
    "completion_percent": 75,
    "quizzes_completed": 2,
    "quiz_average_percent": 80.0,
    "interviews_completed": 1,
    "interview_scores": [82],
    "synced_at": "2026-10-20T15:00:00Z"
  }
  ```

---

### HTTP Status Codes

- `200 OK`: Request succeeded.
- `201 Created`: Resource successfully created.
- `206 Partial Content`: Byte-range video streaming response.
- `400 Bad Request`: Validation failure or missing required fields.
- `403 Forbidden`: Action blocked by security rule, CSRF protection, or read-only restriction.
- `404 Not Found`: Target resource does not exist or belongs to another user.
- `413 Payload Too Large`: Uploaded file exceeds size constraints.
- `415 Unsupported Media Type`: File format not accepted.
- `429 Too Many Requests`: Rate limit exceeded (30 requests/minute per user).
- `502 Bad Gateway`: Upstream LLM provider failure; application falls back to demo mode.
