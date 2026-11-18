"""Konsol penceresi açmadan çalışan köprü girişi (renkolcum-kopru.exe)."""
import os
import sys

if sys.stdout is None:  # --noconsole derlemede
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")

from renkolcum.cli import main  # noqa: E402

main()
