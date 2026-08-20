"""Test wiring for the portal.

The portal package imports `obs_common` and `correlate_events` from tools/,
exactly as it does at runtime, so the tests exercise the real import path
rather than a stubbed one.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import pytest  # noqa: E402

from portal.app import config  # noqa: E402


class Headers(dict):
    """A case-insensitive stand-in for http.client.HTTPMessage."""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


@pytest.fixture
def headers():
    return Headers()


@pytest.fixture
def settings(tmp_path):
    """Fixture mode, and deliberately pointed at a generated/ that does NOT exist.

    Forcing the report fallback is the point: the offline portal must work from
    a clean clone, where `generated/` has never been built.
    """
    s = config.from_env()
    s.mode = "fixtures"
    s.generated_dir = tmp_path / "no-generated-dir"
    return s
