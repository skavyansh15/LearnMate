"""All settings in one place. Secrets come ONLY from environment variables (.env file locally)."""
import os
import secrets
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

BASE = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE / "data"))   # per-user files live here
USERS_DIR = DATA_DIR / "users"
DEMO_DIR = BASE / "demo_course"                          # shipped sample course (read-only)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()    # optional PostgreSQL (e.g. Supabase / Neon)

# ---- ONE configurable AI API (any OpenAI-compatible /chat/completions endpoint) ----
LLM_API_KEY = os.getenv("LLM_API_KEY", "")               # empty -> demo mode
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")  # NVIDIA NIM endpoint
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")  # NVIDIA model: openai/gpt-oss-20b
FORCE_DEMO = os.getenv("DEMO_MODE", "") == "1"           # DEMO_MODE=1 ignores the key

# ---- Web app ----
_raw_secret = os.getenv("SECRET_KEY", "").strip()
if not _raw_secret or _raw_secret in ("change-me", "learnmate-secret-key-3.8-flash-ai", "secret", "dev"):
    SECRET_KEY = secrets.token_hex(32)
else:
    SECRET_KEY = _raw_secret
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "") == "1"          # set to 1 when served over https

# ---- Cost control ----
DAILY_AI_CALLS = int(os.getenv("DAILY_AI_CALLS", "100")) # per user per day; then demo answers
RATE_PER_MIN = int(os.getenv("RATE_PER_MIN", "30"))      # requests per user per minute
CONTEXT_CHARS = int(os.getenv("CONTEXT_CHARS", "20000")) # large context window sent to the AI
MAX_TOKENS_ANSWER = 2048
MAX_TOKENS_STUDY = 3000
CACHE_SIZE = 200                                         # identical AI requests are answered from memory

# ---- Retrieval ----
TOP_K = 8
WINDOW_S = 90            # always include the last 90 s of transcript
CHUNK_MIN_S, CHUNK_MAX_S = 30, 60
MAX_QUESTION_CHARS = 500

# ---- Upload limits ----
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))   # allow local video files up to 500MB
MAX_PAGES = 300
MAX_TEXT_CHARS = 1_500_000
MAX_COURSES_PER_USER = 10
MAX_DOCS_PER_COURSE = 8
