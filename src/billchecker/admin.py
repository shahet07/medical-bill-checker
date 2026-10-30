"""Admin command line (see scripts/admin.py). Prints no document content."""

import argparse
import json
import os
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .auth import hash_password
from .store import Store, load_key


def _store() -> Store:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return Store(url, load_key(os.environ.get("BILLCHECKER_KEY")), pool_size=2)


def stats(store: Store, days: int) -> None:
    q = store._q
    print("Users: {}   (research consent: {})".format(
        q("SELECT count(*) AS n FROM users")[0]["n"], q("SELECT count(*) AS n FROM users WHERE research_consent")[0]["n"]))
    by_status = q("SELECT status, count(*) AS n FROM cases GROUP BY status ORDER BY status")
    print("Saved cases: " + (", ".join("{} {}".format(r["n"], r["status"]) for r in by_status) or "none"))
    print("Research records: {}".format(q("SELECT count(*) AS n FROM research_cases")[0]["n"]))

    since = datetime.now(timezone.utc) - timedelta(days=days)
    counts = store.event_counts(since=since)
    print("\nUsage, last {} days:".format(days))
    for name, n in counts.items():
        print("  {:<20} {}".format(name, n))
    active = q("SELECT count(DISTINCT user_key) AS n FROM events WHERE created_at >= %s AND user_key IS NOT NULL", (since,))
    print("  {:<20} {}".format("active users", active[0]["n"]))

    rows = store.feedback_rows()
    by_rule = defaultdict(Counter)
    for r in rows["flags"]:
        by_rule[(r["rule"], r["confidence"])][r["verdict"]] += 1
    print("\nFlag feedback (precision = correct / (correct + incorrect)):")
    print("  {:<22} {:<7} {:>7} {:>9} {:>6} {:>10}".format("rule", "conf", "correct", "incorrect", "unsure", "precision"))
    for (rule, conf), c in sorted(by_rule.items()):
        judged = c["correct"] + c["incorrect"]
        prec = "{:.0%}".format(c["correct"] / judged) if judged else "-"
        print("  {:<22} {:<7} {:>7} {:>9} {:>6} {:>10}".format(rule, conf, c["correct"], c["incorrect"], c["unsure"], prec))

    survey = rows["survey"]
    print("\nSurvey responses: {}".format(len(survey)))
    if survey:
        print("  average helpfulness (1-5): {:.1f}".format(sum(r["helpful"] for r in survey) / len(survey)))
        for answer, n in Counter(r["most_useful"] for r in survey).most_common():
            print("  most useful = {:<12} {}".format(answer, n))


def reset_password(store: Store, email: str) -> None:
    user = store.get_user_by_email(email)
    if user is None:
        raise SystemExit("No account for {}".format(email))
    temp = "-".join(secrets.token_urlsafe(4) for _ in range(4))
    store.set_password(user.user_id, hash_password(temp))
    store.delete_sessions(user.user_id)
    print("Temporary password for {}: {}".format(user.email, temp))
    print("Give it to them privately and ask them to change it under My account.")


def delete_user(store: Store, email: str, yes: bool) -> None:
    user = store.get_user_by_email(email)
    if user is None:
        raise SystemExit("No account for {}".format(email))
    if not yes:
        raise SystemExit("This deletes {} and all their data. Re-run with --yes to confirm.".format(user.email))
    store.delete_user(user.user_id)
    print("Deleted {}".format(user.email))


def export_research(store: Store, out: str) -> None:
    rows = store.research_rows()
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps({"research_id": r["research_id"], "month": r["month"], **r["data"]}) + "\n")
    print("Wrote {} records to {}".format(len(rows), out))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="admin", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("stats")
    p.add_argument("--days", type=int, default=30)
    sub.add_parser("reset-password").add_argument("email")
    p = sub.add_parser("delete-user")
    p.add_argument("email")
    p.add_argument("--yes", action="store_true")
    sub.add_parser("export-research").add_argument("out")
    args = ap.parse_args(argv)

    store = _store()
    try:
        if args.cmd == "stats":
            stats(store, args.days)
        elif args.cmd == "reset-password":
            reset_password(store, args.email)
        elif args.cmd == "delete-user":
            delete_user(store, args.email, args.yes)
        elif args.cmd == "export-research":
            export_research(store, args.out)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
