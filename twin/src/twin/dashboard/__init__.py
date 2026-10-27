"""The live dashboard (R3): a city map and a timeline of reading -> verdict -> decision -> action.

The map and the timeline come from the run logs (see runlog.py for the format). Since 27 Oct it ALSO reads the Twin's
live feed (/events) for the newest sensor values (live.py), so a calm Twin no longer looks dead. It never calls an MCP tool,
never changes anything in the Twin, and never touches a true value: the Twin's private truth file is skipped on purpose.
Start it with:  python -m twin.dashboard
"""
