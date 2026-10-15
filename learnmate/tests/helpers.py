import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import llm  # noqa: E402
import store  # noqa: E402

H = {"X-Requested-With": "fetch"}
DEMO = "demo-python-lists"


class Base(unittest.TestCase):
    """Every test gets an empty temporary data folder, demo mode, and clean counters."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for patcher in (mock.patch.object(config, "USERS_DIR", Path(self.tmp.name) / "users"),
                        mock.patch.object(config, "LLM_API_KEY", ""), mock.patch.object(config, "FORCE_DEMO", False),
                        mock.patch.object(config, "DAILY_AI_CALLS", 60), mock.patch.object(config, "RATE_PER_MIN", 1000)):
            patcher.start()
            self.addCleanup(patcher.stop)
        llm._cache.clear()
        store._hits.clear()
        self.addCleanup(self.tmp.cleanup)
        self.uid = store.new_uid()
        self.demo = store.demo_course()

    def live(self, reply="x [1]"):
        """Pretend an API key exists and the AI answers `reply`. Returns the mock so tests can read the prompt."""
        patch_key = mock.patch.object(config, "LLM_API_KEY", "test-key")
        patch_key.start()
        self.addCleanup(patch_key.stop)
        fake = mock.patch.object(llm, "complete", return_value=reply)
        m = fake.start()
        self.addCleanup(fake.stop)
        return m
