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
city-brain-convergence/
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
git clone https://github.com/CodeSailor411/city-brain-convergence.git
cd city-brain-convergence
```

Each team works inside its assigned layer folder and coordinates shared changes with the triplet. Team member usernames and CODEOWNERS assignments will be added when confirmed.

## Current status

This repository contains the initial folder structure. Apart from this README, files are empty placeholders, including the report, pitch, interface cards, and Compose file. Empty folders contain `.gitkeep` so Git tracks them.

Application startup instructions will be added once the layers are implemented. The repository will be named `triplet-XX` once the triplet number is confirmed.
