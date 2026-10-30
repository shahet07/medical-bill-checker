"""Summarize validation feedback: how often each flag type was judged right.

Reads only the feedback tables, which hold no document content, so no
encryption key is needed.

    .venv/bin/python scripts/feedback_report.py [~/.billchecker/data]
"""

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".billchecker" / "data").expanduser()
    path = root / "index.sqlite3"
    if not path.exists():
        sys.exit("No data found at {}".format(path))
    db = sqlite3.connect(str(path))
    by_rule = defaultdict(Counter)
    for rule, confidence, verdict in db.execute("SELECT rule, confidence, verdict FROM flag_feedback"):
        by_rule[(rule, confidence)][verdict] += 1

    print("Flag feedback (precision = correct / (correct + incorrect))\n")
    print("{:<22} {:<7} {:>7} {:>9} {:>6} {:>10}".format("rule", "conf", "correct", "incorrect", "unsure", "precision"))
    for (rule, conf), c in sorted(by_rule.items()):
        judged = c["correct"] + c["incorrect"]
        prec = "{:.0%}".format(c["correct"] / judged) if judged else "-"
        print("{:<22} {:<7} {:>7} {:>9} {:>6} {:>10}".format(rule, conf, c["correct"], c["incorrect"], c["unsure"], prec))

    rows = db.execute("SELECT helpful, most_useful FROM survey").fetchall()
    print("\nSurvey responses: {}".format(len(rows)))
    if rows:
        print("Average helpfulness (1-5): {:.1f}".format(sum(r[0] for r in rows) / len(rows)))
        for answer, n in Counter(r[1] for r in rows).most_common():
            print("  most useful = {:<12} {}".format(answer, n))


if __name__ == "__main__":
    main()
