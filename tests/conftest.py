from __future__ import annotations

import os
import tempfile

os.environ["NOVA_DATA_DIR"] = tempfile.mkdtemp(prefix="nova-tests-")
os.environ["NOVA_APP_SECRET"] = "test-secret-that-is-at-least-thirty-two-characters"
os.environ["NOVA_SETUP_TOKEN"] = "test-setup-token"
os.environ["NOVA_COOKIE_SECURE"] = "false"
