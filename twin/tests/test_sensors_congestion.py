"""congestion_index (added 23 Oct for CIVIS and 9antra): a percent sensor on every traffic node."""
from twin.settings import load_config
from twin.generator import generate
from twin.sensors import SensorModel, devices_from_nodes
from twin.sim import sensor_domains


def _world():
    cfg = load_config("config/twin.yaml")
    topo, _ = generate(cfg)
    devs = devices_from_nodes(topo.nodes, sensor_domains(cfg))
    return cfg, topo, devs, SensorModel(cfg.seed, cfg.sensor_model, devs)


def test_every_traffic_node_has_the_three_traffic_sensors_and_congestion_is_in_percent():
    _, topo, devs, _ = _world()
    traffic_nodes = [n for n in topo.nodes if "traffic" in n.domains]
    assert len(traffic_nodes) == 11
    for n in traffic_nodes:
        assert {s.name for s in n.sensors} >= {"vehicle_count", "avg_speed", "congestion_index"}
    cong = [d for d in devs if d.sensor == "congestion_index"]
    assert len(cong) == 11 and {d.unit for d in cong} == {"percent"} and {d.domain for d in cong} == {"traffic"}


def test_calm_city_stays_between_0_and_100_and_well_below_the_brain_threshold_of_80():
    _, _, devs, model = _world()
    cong = [d for d in devs if d.sensor == "congestion_index"]
    values = [model.observed_value(d, None, t) for d in cong for t in range(0, 3000, 7)]
    assert min(values) >= 0 and max(values) <= 100
    assert max(values) < 80, "a calm city must not look like a jam to the Brain (its S01 threshold is 80)"


def test_congestion_rises_when_the_cars_on_the_road_rise():
    _, _, devs, model = _world()
    pairs = [(d, next(x for x in devs if x.node_id == d.node_id and x.sensor == "vehicle_count"))
             for d in devs if d.sensor == "congestion_index"]
    d, car = pairs[0]
    ticks = range(0, 2400, 5)
    busy = max(ticks, key=lambda t: model.true_value(car, None, t))
    quiet = min(ticks, key=lambda t: model.true_value(car, None, t))
    assert model.true_value(d, None, busy) > model.true_value(d, None, quiet) + 10


def test_same_seed_gives_the_same_values():
    _, _, devs, model = _world()
    d = next(x for x in devs if x.sensor == "congestion_index")
    assert [model.observed_value(d, None, t) for t in (1, 50, 500)] == [model.observed_value(d, None, t) for t in (1, 50, 500)]
