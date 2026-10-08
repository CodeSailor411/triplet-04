"""actuate: the token gate, idempotency, caps. Unit tests on the ActionBook, one fresh city per test."""
import base64
import itertools

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from twin.actions import ActionBook, BadRequest
from twin.auth import Identity
from twin.generator import generate
from twin.settings import TokensCfg, load_config
from twin.sim import Simulation
from twin.tokens import make_token

BRAIN = Identity.CITY_BRAIN
VALVE, GRID, SIGNAL, DISPATCH = "set_valve_position", "set_grid_switch", "set_signal_plan", "dispatch"
_jti = itertools.count(1)


def world(**edits):
    cfg = load_config()
    for path, value in edits.items():                     # e.g. tokens=TokensCfg(...)
        setattr(cfg, path, value)
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    return sim, ActionBook(topo, cfg, sim)


def claims(sim, action, targets, params, **over):
    c = {"iss": "guardian", "aud": "twin", "jti": f"tk-{next(_jti)}", "run_id": sim.run_id,
         "iat": sim.clock.iso_of(sim.tick), "exp": sim.clock.iso_of(sim.tick + 30),
         "action": action, "targets": targets, "params": params, "score": 0.9}
    c.update(over)
    return c


def act(sim, book, action=VALVE, targets=("WAT-01",), params=None, key=None, token="auto", caller=BRAIN, **claim_over):
    params = {"position": 40} if params is None and action == VALVE else (params or {})
    targets = list(targets)
    if token == "auto":
        token = make_token(claims(sim, action, targets, params, **claim_over))
    return book.actuate(caller, action, targets, params, token, key or f"k-{next(_jti)}")


# ------------------------------------------------------------------ list_actions
def test_list_actions_shows_risk_preview_and_caps():
    _, book = world()
    a = {x.action: x for x in book.list_actions().actions}
    assert {k: v.risk for k, v in a.items()} == {SIGNAL: "R1", VALVE: "R3", GRID: None, DISPATCH: "R2"}
    assert {k: v.preview_required for k, v in a.items()} == {SIGNAL: False, VALVE: True, GRID: True, DISPATCH: False}
    assert {k: v.action_cap for k, v in a.items()} == {SIGNAL: 3, VALVE: 2, GRID: 2, DISPATCH: 2}
    assert a[VALVE].target_nodes == ["SH-03", "SH-04", "WAT-01", "WAT-03"]
    assert [p.name for p in a[DISPATCH].params] == ["unit_type", "destination", "units"]
    assert book.list_actions().token_mode == "unsigned" and book.list_actions().preview_enforced is False


# ------------------------------------------------------------------ happy path
def test_a_valid_request_commits_and_the_actuator_holds_the_value():
    sim, book = world()
    r = act(sim, book, VALVE, ["WAT-01"], {"position": 40})
    assert (r.status, r.action_id, r.code, r.replayed) == ("committed", "ac-00001", None, False)
    assert book.state[("WAT-01", VALVE)] == {"position": 40.0}
    r2 = act(sim, book, SIGNAL, ["TRF-01", "TRF-04"], {"plan": "all_red"})
    assert r2.action_id == "ac-00002" and book.state[("TRF-04", SIGNAL)] == {"plan": "all_red"}


def test_dispatch_takes_a_destination_node_and_units():
    sim, book = world()
    r = act(sim, book, DISPATCH, ["EMG-05"], {"unit_type": "ambulance", "destination": "TRF-01", "units": 2})
    assert r.status == "committed"


# ------------------------------------------------------------------ wrong input = error, not rejection
@pytest.mark.parametrize("kwargs, code", [
    (dict(action="open_the_pod_bay_doors", targets=["WAT-01"]), "UNKNOWN_ACTION"),
    (dict(targets=[]), "INVALID_TARGETS"),
    (dict(targets=["WAT-01", "WAT-01"]), "INVALID_TARGETS"),
    (dict(targets=["TRF-01"]), "INVALID_TARGETS"),                       # a real node, but no valve there
    (dict(targets=["NOPE-99"]), "UNKNOWN_NODE"),
    (dict(params={"position": 140}), "INVALID_PARAMS"),
    (dict(params={"position": "half"}), "INVALID_PARAMS"),
    (dict(params={"position": True}), "INVALID_PARAMS"),                 # a bool is not a number
    (dict(params={}), "INVALID_PARAMS"),                                 # missing
    (dict(params={"position": 40, "speed": 3}), "INVALID_PARAMS"),       # unknown name
])
def test_malformed_requests_fail_with_a_code(kwargs, code):
    sim, book = world()
    base = dict(action=VALVE, targets=["WAT-01"], params={"position": 40})
    base.update(kwargs)
    with pytest.raises(BadRequest) as e:
        book.actuate(BRAIN, base["action"], base["targets"], base["params"], "x", "k1")
    assert e.value.code == code and e.value.message


def test_empty_idempotency_key_is_refused():
    sim, book = world()
    with pytest.raises(BadRequest) as e:
        book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 1}, "x", "")
    assert e.value.code == "INVALID_IDEMPOTENCY_KEY"


# ------------------------------------------------------------------ the token gate (unsigned mode)
def test_token_missing_garbage_and_wrong_shape():
    sim, book = world()
    assert act(sim, book, token=None).code == "TOKEN_MISSING"
    assert act(sim, book, token="   ").code == "TOKEN_MISSING"
    assert act(sim, book, token="not-a-token").code == "TOKEN_INVALID"
    assert act(sim, book, token="a.b.c").code == "TOKEN_INVALID"
    assert act(sim, book, token=make_token({"jti": "only-this"})).code == "TOKEN_INVALID"
    assert act(sim, book, iss="brain").code == "TOKEN_INVALID"
    assert book.state == {} and book.seq == 0                              # nothing ever committed


def test_expired_token():
    sim, book = world()
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}))
    sim.tick = 31                                                          # the token lived 30 simulated seconds
    r = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k")
    assert r.status == "rejected" and r.code == "TOKEN_EXPIRED"


def test_token_for_another_run():
    sim, book = world()
    assert act(sim, book, run_id="run-42-999").code == "TOKEN_WRONG_RUN"


def test_a_token_works_once():
    sim, book = world()
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti="tk-once"))
    assert book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k1").status == "committed"
    again = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k2")      # new key: not a retry
    assert again.code == "TOKEN_REUSED" and book.seq == 1


@pytest.mark.parametrize("what", ["action", "targets", "params"])
def test_token_must_match_the_exact_request(what):
    sim, book = world()
    signed_for = dict(action=VALVE, targets=["WAT-01"], params={"position": 40})
    if what == "action":
        token = make_token(claims(sim, GRID, ["SH-03"], {"state": "open"}))
        r = book.actuate(BRAIN, VALVE, ["SH-03"], {"position": 40}, token, "k")
    elif what == "targets":
        token = make_token(claims(sim, VALVE, ["WAT-01", "WAT-03"], {"position": 40}))
        r = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k")
    else:
        token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 10}))
        r = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 90}, token, "k")
    assert r.status == "rejected" and r.code == "TOKEN_MISMATCH" and book.state == {}


def test_target_order_does_not_matter_and_extra_token_fields_are_ignored():
    sim, book = world()
    token = make_token(claims(sim, SIGNAL, ["TRF-04", "TRF-01"], {"plan": "normal"}, comment="hello"))
    assert book.actuate(BRAIN, SIGNAL, ["TRF-01", "TRF-04"], {"plan": "normal"}, token, "k").status == "committed"


def test_minimum_score_per_risk_level_only_when_configured():
    sim, book = world()
    assert act(sim, book, score=0.01).status == "committed"                # nothing configured: nothing enforced
    cfg = load_config()
    cfg.tokens = TokensCfg(min_score={"R3": 0.8})
    topo, _ = generate(cfg)
    sim2 = Simulation(topo, cfg)
    book2 = ActionBook(topo, cfg, sim2)
    assert act(sim2, book2, score=0.5).code == "TOKEN_SCORE_TOO_LOW"
    assert act(sim2, book2, score=0.85).status == "committed"
    assert act(sim2, book2, SIGNAL, ["TRF-01"], {"plan": "normal"}, score=0.1).status == "committed"    # R1 has no floor


# ------------------------------------------------------------------ idempotency
def test_same_key_same_request_returns_the_first_answer_without_acting_twice():
    sim, book = world()
    first = act(sim, book, key="retry-me", token=make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti="a")))
    sim.tick = 5
    again = act(sim, book, key="retry-me", token=make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti="b")))
    assert again.replayed and again.action_id == first.action_id == "ac-00001" and again.tick == 0
    assert book.seq == 1


def test_a_retry_may_arrive_with_an_expired_or_used_token():
    sim, book = world()
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}))
    first = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k")
    sim.tick = 500                                                         # long after the token expired
    again = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k")
    assert again.replayed and again.action_id == first.action_id


def test_same_key_changed_request_is_rejected():
    sim, book = world()
    first = act(sim, book, key="k", params={"position": 40})
    r = act(sim, book, key="k", params={"position": 90})
    assert r.status == "rejected" and r.code == "IDEMPOTENCY_CONFLICT" and r.details["first_action_id"] == first.action_id
    assert book.state[("WAT-01", VALVE)] == {"position": 40.0}             # the first command still stands


def test_a_rejected_attempt_does_not_use_up_the_key():
    sim, book = world()
    assert act(sim, book, key="k", token=None).code == "TOKEN_MISSING"
    assert act(sim, book, key="k").status == "committed"                   # same key, now with a token: allowed


def test_keys_do_not_leak_between_callers():
    sim, book = world()
    act(sim, book, key="shared-name")
    other = act(sim, book, key="shared-name", params={"position": 90}, caller=Identity.GUARDIAN)
    assert other.status == "committed"                                     # not a conflict, a different caller's key


# ------------------------------------------------------------------ caps
def test_cap_exceeded_refuses_the_whole_request_with_the_agreed_fields():
    sim, book = world()
    three_valves = ["WAT-01", "WAT-03", "SH-03"]
    r = act(sim, book, VALVE, three_valves, {"position": 10})
    assert r.status == "rejected" and r.code == "CAP_EXCEEDED"
    d = r.details
    assert (d["domain"], d["cap"], d["in_use"], d["requested"], d["remaining"]) == ("water", 2, 0, 3, 2)
    assert book.state == {} and book.seq == 0                              # nothing was applied, not even the first two
    assert act(sim, book, VALVE, three_valves[:2], {"position": 10}).status == "committed"     # exactly the cap is fine


def test_traffic_cap_is_three():
    sim, book = world()
    assert act(sim, book, SIGNAL, ["TRF-01", "TRF-04", "TRF-05", "TRF-06"], {"plan": "normal"}).details["cap"] == 3
    assert act(sim, book, SIGNAL, ["TRF-01", "TRF-04", "TRF-05"], {"plan": "normal"}).status == "committed"


def test_a_shared_node_counts_in_every_domain_it_belongs_to():
    sim, book = world()
    # SH-03 and SH-04 are both water AND power nodes. A valve request on them is 2 in water and 2 in power.
    assert act(sim, book, VALVE, ["SH-03", "SH-04"], {"position": 10}).status == "committed"
    book.caps["power"]["action_cap"] = 1                                   # tighten the OTHER domain's cap
    r = act(sim, book, VALVE, ["SH-03", "SH-04"], {"position": 20})
    assert r.code == "CAP_EXCEEDED" and r.details["domain"] == "power" and r.details["requested"] == 2
    assert [v["domain"] for v in r.details["violations"]] == ["power"]


def test_a_token_refused_for_caps_is_not_spent():
    sim, book = world()
    targets = ["WAT-01", "WAT-03", "SH-03"]
    token = make_token(claims(sim, VALVE, targets, {"position": 10}, jti="keep-me"))
    assert book.actuate(BRAIN, VALVE, targets, {"position": 10}, token, "k").code == "CAP_EXCEEDED"
    book.caps["water"]["action_cap"] = 3                                   # the situation changes
    assert book.actuate(BRAIN, VALVE, targets, {"position": 10}, token, "k2").status == "committed"


def test_token_is_checked_before_caps():
    """Someone without a valid token learns nothing about the caps."""
    sim, book = world()
    assert act(sim, book, VALVE, ["WAT-01", "WAT-03", "SH-03"], {"position": 10}, token=None).code == "TOKEN_MISSING"


# ------------------------------------------------------------------ new run wipes the slate
async def test_a_new_run_clears_actions_and_spent_tokens():
    sim, book = world()
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti="same-jti"))
    assert book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k").action_id == "ac-00001"
    await sim.reset()
    assert act(sim, book, jti="same-jti").status == "committed"            # fresh run id, jti forgotten
    assert book.seq == 1 and len(book.state) == 1


# ------------------------------------------------------------------ signed mode
def _signed_world():
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    sim, book = world(tokens=TokensCfg(mode="signed", guardian_public_key=pub))
    return key, sim, book


def test_signed_mode_accepts_a_real_signature():
    key, sim, book = _signed_world()
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}), key)
    assert book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "k").status == "committed"


def test_signed_mode_refuses_everything_else():
    key, sim, book = _signed_world()
    good = claims(sim, VALVE, ["WAT-01"], {"position": 40})
    stranger = make_token(good, Ed25519PrivateKey.generate())               # signed by someone else
    unsigned = make_token(good)                                             # alg none
    head, body, sig = make_token(good, key).split(".")
    tampered = make_token({**good, "params": {"position": 99}}, key).split(".")[1]
    forged = ".".join([head, tampered, sig])                                # payload swapped after signing
    for token in (stranger, unsigned, forged):
        r = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 99 if token is forged else 40}, token, f"k{id(token)}")
        assert r.status == "rejected" and r.code == "TOKEN_INVALID"
    assert book.seq == 0


def test_unsigned_mode_refuses_a_signed_token_and_the_mode_comes_from_config_only():
    sim, book = world()
    key = Ed25519PrivateKey.generate()
    r = book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}), key), "k")
    assert r.code == "TOKEN_INVALID"


def test_signed_mode_needs_a_real_public_key():
    with pytest.raises(ValueError, match="32-byte"):
        TokensCfg(mode="signed", guardian_public_key="bm9wZQ==")
