"""Uvicorn entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure `app` package is importable regardless of where we're invoked from.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    log_level = os.getenv("LOG_LEVEL", "info")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=os.getenv("RELOAD", "false").lower() == "true",
        app_dir=str(HERE),
    )


if __name__ == "__main__":
    main()
