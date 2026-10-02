# Brain Interface Card â€” draft

Owner/team: Civis.
Role: incident detection and response decisions.

## Sends and receives
Define each input/output, required fields, units, errors, and timeout behavior. Synthetic examples are in `mocks/partners.json`; these are provisional, not a binding contract.

## Partner configuration
Partner endpoints and credentials must come from configuration. `.env.example` proposes variable names. Explain how to switch partners once the adapter is implemented.

## Authentication
Not implemented. Agree authentication and authorization with the triplet; never hard-code credentials. Define rejection behavior for missing/invalid credentials.

## Independent operation
`python src/main.py` checks offline partner fixtures. A real standalone demonstration with functioning domain logic and both partner mocks is still required.
