"""Write the synthetic test documents to fixtures/ so you can open and look at them."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from synthetic import build_files  # noqa: E402

if __name__ == "__main__":
    for f in build_files(ROOT / "fixtures"):
        print("{:<32} {:<5} {:<10} case={}".format(f.path.name, f.kind, f.variant, f.case.name))
