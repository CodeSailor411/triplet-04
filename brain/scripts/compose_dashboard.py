"""Run the pinned Trinity dashboard with Compose-specific health and log handling."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from twin.dashboard.events import Event


def split_sessions(events: list["Event"]) -> list[list["Event"]]:
    """Use Trinity's session rules while indexing the minimum tick of each session."""
    from twin.dashboard.events import TICK_BACK, _is_start, sort_key, wall_time

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
    has_work, newest = False, 0
    for _, event in walled:
        starts = _is_start(event)
        tick = event["tick"]
        if sessions[-1] and ((starts and has_work) or tick < newest - TICK_BACK):
            sessions.append([])
            has_work, newest = False, 0
        sessions[-1].append(event)
        has_work = has_work or not starts
        newest = max(newest, tick)

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
