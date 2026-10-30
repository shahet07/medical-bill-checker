"""Admin tasks against the database. Needs DATABASE_URL and BILLCHECKER_KEY.

    .venv/bin/python scripts/admin.py stats [--days 30]
    .venv/bin/python scripts/admin.py reset-password EMAIL
    .venv/bin/python scripts/admin.py delete-user EMAIL --yes
    .venv/bin/python scripts/admin.py export-research research.jsonl

In Docker:  docker compose -f deploy/docker-compose.yml exec app python -m billchecker.admin stats
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billchecker.admin import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
