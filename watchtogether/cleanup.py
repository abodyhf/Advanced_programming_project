"""For scheduled deletion even while the web server is stopped."""
import os
from pathlib import Path
from .db import Database
from .graph import ROOT

if __name__ == "__main__":
    directory = Path(os.environ.get("WATCHTOGETHER_DATA_DIR", ROOT / "instance"))
    print(f"Deleted {Database(directory / 'watchtogether.sqlite3').cleanup()} expired group(s).")
