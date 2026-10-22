"""Run the unified Guardian, model, simulator, and dashboard service."""
import os

import uvicorn

from unified_api import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
