"""T6 Stuck sensor: a sensor freezes on one value, Guardian cuts it off.

Layers: Twin -> Guardian (the Brain only needs to learn the sensor is cut off).
Trigger: the Twin starts scenario `stuck_sensor` (the sensor keeps repeating its last value).
Expected: Guardian calls `isolate_sensor`, the Twin cuts that sensor off its feed and logs it.

    python scenarios/T6_stuck_sensor_isolated.py                 # our stand-in Guardian isolates it on command
    python scenarios/T6_stuck_sensor_isolated.py --layers real   # the real Guardian must notice and isolate by itself
"""
import _kit as kit


def more_args(ap):
    ap.add_argument("--device", default="WAT-02.water_level", help="which sensor gets stuck (default WAT-02.water_level)")
    ap.add_argument("--wait", type=float, default=30, help="real seconds to wait for the real Guardian (default 30)")


run = kit.begin("T6", "Stuck sensor isolated", __doc__, real_ok=True, extra=more_args)
device = run.args.device
run.scenario("stuck_sensor", {"device_id": device})
if run.real:
    run.wait(run.args.wait, "the real Guardian should notice the frozen sensor")
else:
    run.wait(6, "the sensor freezes after 2 ticks, give it a few more")
    run.stand_in("mock_guardian.py", "isolate", "--devices", device, "--reason", "stuck sensor")
state = run.call("guardian", "get_containment_state")
mine = [d for d in state["devices"] if d["device_id"] == device]
print(f"  containment state of {device}: {mine[0]['state'] if mine else 'not cut off'}")


def checks(events):
    cuts = [e for e in kit.of(events, "twin", "containment") if e["data"].get("tool") == "isolate_sensor"
            and device in e["data"].get("changed", [])]
    return [
        (any(e["data"].get("name") == "stuck_sensor" for e in kit.of(events, "twin", "scenario")), "the Twin started the stuck sensor"),
        (bool(mine) and mine[0]["state"] == "isolated", f"{device} is isolated in the Twin's containment state"),
        (bool(cuts), "the Twin logged the isolation"),
        (bool(kit.of(events, "guardian")), "Guardian wrote events"),
    ]


kit.finish(run, {}, checks)
