# scenarios/

One script per Test Book scenario (rule R2: one trigger, one log file). Each script:

1. checks that the Twin answers (it does **not** start the Twin; if it cannot reach it, it says so and stops with exit code 2),
2. resets the run (new run id, clock at 0, old faults forgotten),
3. pulls its one trigger and waits,
4. merges the part files of every layer into one log and saves it as `logs/<ID>-<n>.jsonl` (for example `logs/T3-1.jsonl`; a second run of T3 becomes `T3-2`),
5. checks the expected result, prints one line per check and a last line `PASS` or `FAIL`, and adds a row to `logs/INDEX.md`.

Exit codes: `0` passed, `1` a check failed, `2` setup problem (Twin not running, a stand-in crashed, merge failed).

## How to run

Terminal 1, start the Twin (from the `twin/` folder, so its log files land where the scripts look):

```
cd twin
python -m twin
```

Terminal 2, from the repo root, with the same Python environment as the Twin:

```
python scenarios/T1_calm_day.py
python scenarios/T2_real_jam.py
...
```

`--help` on any script shows its options. The Twin's address comes from `--url`, then `TWIN_URL`, then `twin/config/twin.yaml`; the keys from the environment or `twin/.env`. Nothing is hard-coded.

## The seven scenarios

| ID | Script | Layers | What it shows | Real layers possible? |
|---|---|---|---|---|
| T1 | `T1_calm_day.py` | Twin, Brain | Nothing happens, so the Brain must not act. About 20 s | yes (`--layers real`) |
| T2 | `T2_real_jam.py` | all three | Real jam, Guardian signs, Brain acts, Twin commits. About 15 s | yes |
| T3 | `T3_fake_jam_refused.py` | Twin, Guardian, Brain | A sensor lies, Guardian refuses, nothing is sent, a person is asked | yes |
| T4 | `T4_guardian_silent.py` | Twin, Brain, Guardian | Guardian never answers, the Brain gives up, logs it and asks a person | no (see below) |
| T5 | `T5_token_replay.py` | Guardian, Twin | One token used twice: second use is `TOKEN_REUSED` | no |
| T6 | `T6_stuck_sensor_isolated.py` | Twin, Guardian | A frozen sensor is isolated and cut off the feed | yes |
| T7 | `T7_repeated_command_once.py` | Brain, Twin | The same command sent twice runs once | no |

## Stand-ins or real layers

* **Default (`--layers standin`):** our stand-ins from `twin/mocks/` play the Brain and the Guardian. The script starts them itself. Every stand-in event carries `stand_in: true`. The Brain to Guardian network call is **not** tested this way, because the stand-in Guardian lives inside the stand-in Brain.
* **`--layers real` (T1, T2, T3, T6):** the partners' real Brain and Guardian must already be running and watching this Twin. The script only pulls the trigger on the Twin, waits (`--wait`), and reads the logs. It finds their part files in `brain/run-logs/` and `guardian/run-logs/` (the agreed place), or you pass them with `--parts FILE ...`. A part file only merges if its `run_id` equals the Twin's current one, so the real layers must follow the new run id after the reset. If a real layer writes no events, the matching check fails on purpose: it means R3 would show a hole.
* T4, T5 and T7 are stand-ins only: they test the Twin's own rules (timeout handling around a silent partner, trust gate, idempotency) and need a partner we control.
* **The real-layer mode has not been run against the real Brain or Guardian.** It was only tried with no partner running (it fails with clear messages, it does not crash).

Every row in `logs/INDEX.md` says, per layer, `stand-in`, `real`, `mixed` or `no events`. The label is read from the events themselves, so it cannot be wrong by a forgotten flag.

## Things to know

* The Twin also writes its own merged copy `logs/run-42-NNN.jsonl` whenever a run ends (reset, stop, shutdown). Those are the same events, without a scenario name. The dashboard ignores duplicates. Commit only the `T*-*.jsonl` files and `INDEX.md`.
* T1 is a calm run, so its log is short (the run start and end). That is the point: nothing happened. T1 ends by resetting the run, because a calm Twin writes no log file until a run ends.
* A failed run is saved too (labelled `FAIL` in the index), so a failure leaves evidence.
* Owner of `scenarios/` and `logs/`: the Twin team.
