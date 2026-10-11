# CIVIS and Trinity mock packages

These are the two tagged mocks available for partner testing. Each ZIP contains only its layer folder, with the original source, configuration examples, dependencies, tests and launch instructions.

| Team | Package | Source tag | Source commit |
| --- | --- | --- | --- |
| CIVIS, Brain | [brain-mock-1.zip](brain-mock-1.zip) | [brain-mock-1](https://github.com/CodeSailor411/triplet-04/tree/brain-mock-1) | f3cc67e3f66fd19d5d3dbc957b98f4b742a08b65 |
| Trinity, Twin | [twin-mock-1.zip](twin-mock-1.zip) | [twin-mock-1](https://github.com/CodeSailor411/triplet-04/tree/twin-mock-1) | 9170ee2404face946a346711e1739d0c405052c1 |

Download both ZIP files and extract them into the same empty folder. This creates sibling brain/ and twin/ folders. Follow each extracted README.md for installation and startup; each layer uses its own Python environment and local .env.

Every packaged file matches its source tag byte for byte. [SHA256SUMS.txt](SHA256SUMS.txt) records the package checksums. No local secrets, virtual environments or runtime logs are included.

Brain is the approved limited mock. Its remaining integration gaps are documented inside brain/docs/mock-team/HANDOVER.md. The packages do not certify a complete three-layer integration.

Later checkpoints should use new names such as brain-mock-2 and twin-mock-2, preserving these snapshots.
