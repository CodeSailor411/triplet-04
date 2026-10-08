"""python -m twin   starts the Twin using config/twin.yaml and your .env."""
import logging

import uvicorn

from .settings import ConfigError, load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1
    from .app import create_app
    uvicorn.run(create_app(settings), host=settings.config.server.host, port=settings.config.server.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
