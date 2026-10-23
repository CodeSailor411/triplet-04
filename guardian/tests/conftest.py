"""Use the explicitly local demo mode for legacy in-process API tests."""
import os

os.environ.setdefault("DEMO_MODE", "true")
