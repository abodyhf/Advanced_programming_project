"""Start WatchTogether: python app.py (Python 3.11+)."""
import argparse
import os
import uvicorn
from watchtogether.api import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WatchTogether movie night app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, access_log=False)
