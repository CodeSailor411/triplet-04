"""
Demo: simulates a Twin sending sensor readings to Guardian, both normal
and a spoofed "fire" reading with no corroborating evidence.

Run Guardian first in another terminal:
    uvicorn guardian.main:app --port 8001

Then run this:
    python demo.py
"""

import time
import requests

BASE = "http://127.0.0.1:8001"


def ingest(sensor_id, sensor_type, value, unit, seq, incident_type=None, ts=None):
    payload = {
        "sensor_id": sensor_id,
        "sensor_type": sensor_type,
        "value": value,
        "unit": unit,
        "timestamp": ts if ts is not None else time.time(),
        "location": {"lat": 37.27, "lng": 9.87},  # Bizerte, for flavor
        "sequence_number": seq,
        "incident_type": incident_type,
    }
    r = requests.post(f"{BASE}/ingest", json=payload)
    print(f"[{sensor_id:18s}] -> {r.status_code} {r.json()}")
    return r.json()


def main():
    print("=== Phase 1: normal baseline readings (no incident) ===")
    now = time.time()
    for i in range(6):
        ingest("air_quality_01", "air_quality", 40 + i, "AQI", seq=i, ts=now + i)

    print("\n=== Phase 2: REAL fire -- temp spike WITH corroborating smoke/AQI rise ===")
    fire_time = now + 100
    # air quality spikes first (smoke)
    ingest("air_quality_01", "air_quality", 180, "AQI", seq=10, ts=fire_time - 5)
    # emergency calls come in
    ingest("emergency_call_04", "emergency_call", 12, "calls/min", seq=1, ts=fire_time + 5)
    # the "fire" signal itself -- here we use power_load as our proxy incident trigger
    result = ingest("power_load_09", "power_load", 30, "kW", seq=1, ts=fire_time,
                     incident_type="fire")
    print(f"  --> Verdict for genuine fire signal: {result['verdict']['verdict']} "
          f"(score={result['verdict']['trust_score']})")

    print("\n=== Phase 3: SPOOFED fire -- isolated signal, nothing corroborates it ===")
    spoof_time = now + 300
    result = ingest("power_load_09", "power_load", 4900, "kW", seq=2, ts=spoof_time,
                     incident_type="fire")
    print(f"  --> Verdict for spoofed fire signal: {result['verdict']['verdict']} "
          f"(score={result['verdict']['trust_score']}, reasons={result['verdict']['reasons']})")

    print("\n=== Phase 4: replay attack -- resending an old sequence number ===")
    r = requests.post(f"{BASE}/ingest", json={
        "sensor_id": "power_load_09",
        "sensor_type": "power_load",
        "value": 30,
        "unit": "kW",
        "timestamp": spoof_time,
        "location": {"lat": 37.27, "lng": 9.87},
        "sequence_number": 1,  # already used -- should be rejected
    })
    print(f"[replay attempt      ] -> {r.status_code} {r.json()}")

    print("\n=== Phase 5: check reputation after the spoof ===")
    r = requests.get(f"{BASE}/reputation/power_load_09")
    print(r.json())


if __name__ == "__main__":
    main()
