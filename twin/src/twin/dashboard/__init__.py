"""The live dashboard (R3): a city map and a timeline of reading -> verdict -> decision -> action.

It only READS the run logs (see runlog.py for the format). It never calls the Twin and never touches a true value:
the Twin's private truth file is skipped on purpose. Start it with:  python -m twin.dashboard
"""
