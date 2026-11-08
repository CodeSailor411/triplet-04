"""Run the pinned Trinity dashboard with a lightweight Compose health route."""

from nicegui import app
from twin.dashboard.__main__ import main


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "trinity-dashboard"}


if __name__ == "__main__":
    main()
