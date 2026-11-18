"""Run one service: python -m lighthouse.services gateway (SERVICE env also works)."""
import os
import sys

import uvicorn

from lighthouse.services.app import create_app

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else os.environ["SERVICE"]
    uvicorn.run(create_app(name), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="warning")
