"""Start the dashboard:

    python -m twin.dashboard                 read the run logs listed in config/twin.yaml (dashboard.sources)
    python -m twin.dashboard --sample        look at a made-up run (Twin events are real, Guardian and Brain events are invented)
    python -m twin.dashboard --sources a b   read these folders or files instead
    python -m twin.dashboard --no-feed       do not read the Twin's live feed (logs only)

Then open http://127.0.0.1:8080 in a browser. It needs no internet.
"""
import argparse
import asyncio
import tempfile
from pathlib import Path

from nicegui import app, ui

from ..generator import fingerprint, generate
from ..settings import load_config
from .live import LiveFeed, find_key
from .page import Hub, build_page
from .sample import write_sample


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m twin.dashboard", description=__doc__.split("\n\n")[0])
    ap.add_argument("--sample", action="store_true", help="show a made-up run")
    ap.add_argument("--sources", nargs="+", help="folders or files with run logs")
    ap.add_argument("--no-feed", action="store_true", help="do not read the Twin's live feed")
    ap.add_argument("--feed-url", help="where the Twin runs (default: from `server` in config/twin.yaml)")
    ap.add_argument("--feed-key", help="key for the live feed (default: TWIN_KEY_CITY_BRAIN from the environment or twin/.env)")
    ap.add_argument("--port", type=int)
    ap.add_argument("--host")
    a = ap.parse_args(argv)
    cfg = load_config()
    topology, layout = generate(cfg)
    sources = a.sources
    if a.sample:
        tmp = Path(tempfile.mkdtemp(prefix="twin-sample-"))
        write_sample(tmp)
        sources = [str(tmp)]
        print(f"Sample run written to {tmp}")
    app.add_static_files("/tw-fonts", str(Path(__file__).parent / "fonts"))     # Lato, served by the dashboard itself: no internet needed
    live = None
    if cfg.dashboard.live_feed and not a.no_feed and not a.sample:        # the sample is made-up data: no live values next to it
        base = a.feed_url or cfg.dashboard.feed_url or f"http://{cfg.server.host}:{cfg.server.port}"
        live = LiveFeed(base, find_key(a.feed_key))
        if live.enabled:
            app.on_startup(lambda: asyncio.create_task(live.run()))       # the reader runs in the background, inside the page's loop
        else:
            print(f"Live feed is off: {live.error}")
    hub = Hub(cfg.dashboard, topology, layout, sources=sources, fingerprint=fingerprint(topology), live=live)
    ui.run(lambda: build_page(hub), host=a.host or cfg.dashboard.host, port=a.port or cfg.dashboard.port,
           title="Triplet 04 · Twin dashboard", reload=False, show=False, favicon="🏙️")


if __name__ in {"__main__", "__mp_main__"}:
    main()
