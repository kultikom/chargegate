# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 KultiKom GmbH & Co. KG – see LICENSE
"""Test setup: fresh SQLite database and the app folder on the import path (before any app import)."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["ADMIN_PASSWORD"] = "test-password-123"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chargegate" / "app"))
