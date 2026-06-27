"""DB_TABLE_PREFIX: the app can target a prefixed schema (standalone deploy).

Settings are read at import time, so the prefix is exercised in a fresh
subprocess. With the default (empty) prefix the rest of the suite already proves
the unprefixed path; here we prove the prefixed path resolves table names + FKs.
"""

from __future__ import annotations

import os
import subprocess
import sys

_SCRIPT = """
import app.models  # register all models
from sqlalchemy import create_engine
from app.core.db import Base
from app.models.content import Space, Page

assert Space.__tablename__ == "Docs_space", Space.__tablename__
# A foreign key target must also be prefixed for the mapper to configure.
fk = next(iter(Page.__table__.c.book_id.foreign_keys))
assert fk.target_fullname == "Docs_book.id", fk.target_fullname

# All tables + FKs resolve and create cleanly under the prefix (SQLite is enough
# to prove the schema is internally consistent).
engine = create_engine("sqlite://")
Base.metadata.create_all(engine)
names = sorted(t.name for t in Base.metadata.sorted_tables)
assert all(n.startswith("Docs_") for n in names), names
print("OK", len(names))
"""


def test_table_prefix_applied_in_subprocess() -> None:
    env = {**os.environ, "DB_TABLE_PREFIX": "Docs_"}
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("OK")
