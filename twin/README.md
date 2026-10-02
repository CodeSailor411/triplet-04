# Twin layer

Owner: **Trinity**. Team members make changes inside this layer folder.

Run independently: `python twin/src/main.py` from the repo root, or `python src/main.py` from this folder. This checks local synthetic partner fixtures, not a working layer service. Python 3.11+; no third-party packages.

Implement domain logic in `src/`, retain stand-ins for brain and guardian in `mocks/`, and add behavior tests in `tests/`. Update INTERFACE.md before integration. Copy `.env.example` to `.env` when implementing your configuration adapter; the current fixture runner does not read environment variables.
