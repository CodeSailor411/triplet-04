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

These commands are the stand-in way to run the scenarios. For the live run with all three real layers (T2 and T3), use the Compose launcher from the root README: `python brain/scripts/compose_stack.py t2` and `t3`.

## The eight scenarios

| ID | Script | Layers | What it shows | Real layers possible? |
|---|---|---|---|---|
| T1 | `T1_calm_day.py` | Twin, Brain | Nothing happens, so the Brain must not act. About 20 s | yes (`--layers real`) |
| T2 | `T2_real_jam.py` | all three | Real jam, Guardian signs, Brain acts, Twin commits. About 15 s | yes |
| T3 | `T3_fake_jam_refused.py` | Twin, Guardian, Brain | A sensor lies, Guardian refuses, nothing is sent, a person is asked | yes |
| T4 | `T4_guardian_silent.py` | Twin, Brain, Guardian | Guardian never answers, the Brain gives up, logs it and asks a person | no (see below) |
| T5 | `T5_token_replay.py` | Guardian, Twin | One token used twice: second use is `TOKEN_REUSED` | yes, real Guardian, no Brain (see below) |
| T6 | `T6_stuck_sensor_isolated.py` | Twin, Guardian | A frozen sensor is isolated and cut off the feed | yes |
| T7 | `T7_repeated_command_once.py` | Brain, Twin | The same command sent twice runs once | no |
| T8 | `T8_tampered_token.py` | Guardian, Twin | One valid control request commits once. A second request, whose token had its signature changed after the Guardian issued it, is refused with `TOKEN_INVALID` and has no effect | yes, real Guardian, no Brain (see below) |

## Stand-ins or real layers

* **Default (`--layers standin`):** our stand-ins from `twin/mocks/` play the Brain and the Guardian. The script starts them itself. Every stand-in event carries `stand_in: true`. The Brain to Guardian network call is **not** tested this way, because the stand-in Guardian lives inside the stand-in Brain.
* **`--layers real` (T1, T2, T3, T6):** the partners' real Brain and Guardian must already be running and watching this Twin. The script only pulls the trigger on the Twin, waits (`--wait`), and reads the logs. It finds their part files in `brain/run-logs/` and `guardian/run-logs/` (the agreed place), or you pass them with `--parts FILE ...`. A part file only merges if its `run_id` equals the Twin's current one, so the real layers must follow the new run id after the reset. If a real layer writes no events, the matching check fails on purpose: it means R3 would show a hole.
* T4 and T7 are stand-ins only: they test the Twin's own rules (timeout handling around a silent partner, idempotency) and need a partner we control.
* T5 and T8 talk to the real Guardian through `_real_guardian.py` (a helper, not a scenario). The Guardian must already be running and watching this Twin. The helper reads the Guardian's bearer key (`GUARDIAN_BRAIN_MCP_BEARER_KEY`) from the environment or the `.env` in the repo root and never writes it to a log. No Brain takes part, so the index label for both reads `brain: no events`. Both cover the Twin and the Guardian only.

### What has run against real layers

* **Twin, Guardian and Brain together:** T2 ran on Windows with the Compose launcher. The verified T2 report on `main` (run `run-42-004`) joins the real Twin, Guardian and CIVIS records, including the committed action.
* **T3 live refusal:** the evidence is in PR #43, which is not merged yet. Treat it as pending until it is.
* **Twin and Guardian only (no Brain):** T5 and T8 against the real Guardian on 8 Nov 2026 (`logs/T5-2.jsonl`, `logs/T8-1.jsonl`). T5 shows one commit and a `TOKEN_REUSED` rejection for the same token ID. T8 shows one valid control commit and a `TOKEN_INVALID` rejection for the tampered signature.
* **Not complete:** full joint acceptance across all three real layers for every scenario.

Every row in `logs/INDEX.md` says, per layer, `stand-in`, `real`, `mixed` or `no events`. The label is read from the events themselves, so it cannot be wrong by a forgotten flag.

## Things to know

* The Twin also writes its own merged copy `logs/run-42-NNN.jsonl` whenever a run ends (reset, stop, shutdown). Those are the same events, without a scenario name. The dashboard ignores duplicates. Commit only the `T*-*.jsonl` files and `INDEX.md`.
* T1 is a calm run, so its log is short (the run start and end). That is the point: nothing happened. T1 ends by resetting the run, because a calm Twin writes no log file until a run ends. A T1 log with Twin rows and no Brain rows only supports a Twin-only baseline, so the Test Book marks it Partial.
* A failed run is saved too (labelled `FAIL` in the index), so a failure leaves evidence.