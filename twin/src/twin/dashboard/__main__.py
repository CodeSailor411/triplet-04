"""Start the dashboard:

    python -m twin.dashboard                 read the run logs listed in config/twin.yaml (dashboard.sources)
    python -m twin.dashboard --sample        look at a made-up run (Twin events are real, Guardian and Brain events are invented)
    python -m twin.dashboard --sources a b   read these folders or files instead

Then open http://127.0.0.1:8080 in a browser. It needs no internet.
"""
import argparse
import tempfile
from pathlib import Path

from nicegui import ui

from ..generator import fingerprint, generate
from ..settings import load_config
from .page import Hub, build_page
from .sample import write_sample


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m twin.dashboard", description=__doc__.split("\n\n")[0])
    ap.add_argument("--sample", action="store_true", help="show a made-up run")
    ap.add_argument("--sources", nargs="+", help="folders or files with run logs")
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
    hub = Hub(cfg.dashboard, topology, layout, sources=sources, fingerprint=fingerprint(topology))
    ui.run(lambda: build_page(hub), host=a.host or cfg.dashboard.host, port=a.port or cfg.dashboard.port,
           title="Triplet 04 · Twin dashboard", reload=False, show=False, favicon="🏙️")


if __name__ in {"__main__", "__mp_main__"}:
    main()
