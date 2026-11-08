"""Run the pinned Trinity dashboard with Compose-specific health and log handling."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from twin.dashboard.events import Event


def split_sessions(events: list["Event"]) -> list[list["Event"]]:
    """Split on Twin start markers, since partner events can arrive many ticks late."""
    from twin.dashboard.events import _is_start, sort_key, wall_time

    walled, loose = [], []
    for event in events:
        wall = wall_time(event)
        if wall is None:
            loose.append(event)
        else:
            tick, _, layer, event_id = sort_key(event)
            walled.append(((wall, tick, layer, event_id), event))
    walled.sort(key=lambda item: item[0])

    sessions: list[list["Event"]] = [[]]
    has_work = False
    for _, event in walled:
        starts = event["layer"] == "twin" and _is_start(event)
        if starts and has_work:
            sessions.append([])
            has_work = False
        sessions[-1].append(event)
        has_work = has_work or not starts

    minimums = [min((event["tick"] for event in session), default=float("inf")) for session in sessions]
    for event in loose:
        tick = event["tick"]
        home = next((i for i in range(len(sessions) - 1, -1, -1) if minimums[i] <= tick), 0)
        sessions[home].append(event)
        minimums[home] = min(minimums[home], tick)
    return [sorted(session, key=sort_key) for session in sessions]


def configure_dashboard() -> None:
    from nicegui import app
    from twin.dashboard import page

    # The pinned page imports the splitter directly. Keep the override local to Compose.
    page.split_sessions = split_sessions

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "trinity-dashboard"}


if __name__ == "__main__":
    from twin.dashboard.__main__ import main

    configure_dashboard()
    main()
