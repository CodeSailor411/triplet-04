import argparse
import os
from pathlib import Path

import uvicorn

from civis_brain.settings import load_settings


def main():
    parser = argparse.ArgumentParser(description="Run CIVIS Brain")
    parser.add_argument("--env-file", help="Explicit local environment file, e.g. .env.partner")
    args = parser.parse_args()
    if args.env_file:
        os.environ["CIVIS_ENV_FILE"] = str(Path(args.env_file).expanduser().resolve())
    settings = load_settings()
    uvicorn.run("civis_brain.app:create_app", factory=True, host=settings.brain_host,
                port=settings.brain_port)


if __name__ == "__main__":
    main()
