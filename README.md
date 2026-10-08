# City Brain Convergence

Shared Phase 1 repository for **Civis**, **9antra**, and **Trinity**.

## Teams

| Team | Layer | Folder |
| --- | --- | --- |
| Trinity | Twin — city simulation, sensors, and actuators | [`twin/`](twin/) |
| Civis | City Brain — incident detection and response | [`brain/`](brain/) |
| 9antra | Guardian — data trust, faults, and security | [`guardian/`](guardian/) |

## Repository structure

```text
triplet-04/
├── README.md
├── INTEGRATION.md
├── TESTBOOK.md
├── docker-compose.yml
├── .github/
│   └── CODEOWNERS
├── scenarios/
├── logs/
├── twin/
│   ├── README.md
│   ├── INTERFACE.md
│   ├── src/
│   ├── mocks/
│   └── tests/
├── brain/
│   ├── README.md
│   ├── INTERFACE.md
│   ├── src/
│   ├── mocks/
│   └── tests/
├── guardian/
│   ├── README.md
│   ├── INTERFACE.md
│   ├── src/
│   ├── mocks/
│   └── tests/
├── docs/
│   ├── report.pdf
│   ├── pitch.pdf
│   └── diagrams/
└── mockups/
    └── testing/
```

Each layer's `mocks/` folder is for stand-ins of the other two layers. Root files, `scenarios/`, `logs/`, `docs/`, and `mockups/` are shared by the triplet.

## Get the repository

```sh
git clone https://github.com/CodeSailor411/triplet-04.git
cd triplet-04
```

Each team works inside its assigned layer folder and coordinates shared changes with the triplet. CODEOWNERS assigns Brain/shared files to CodeSailor411, Twin to The1Dali and Guardian to houssembensaid5.

## Current status

The shared layout is scaffolded. CIVIS's primary mock environment, fixed interfaces and four-person work plan are in [brain/](brain/README.md). Elyes's Power/Air Quality scenarios and common runtime/MCP tools are implemented on codex/civis-elyes; the other three workflows remain assigned. Full-release readiness is false. See [handover](brain/docs/mock-team/HANDOVER.md) for launch and current gaps. Twin development currently exists on Trinity's separate development branches; do not assume unmerged branch features are already on the layer branch.

Reports, pitch, shared integration/Test Book and Compose placeholders remain for the triplet's later work. The repository is named `triplet-04`.
