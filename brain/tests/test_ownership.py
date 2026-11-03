import importlib.util
import json
from pathlib import Path

import pytest

brain = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("ownership", brain / "scripts/check_ownership.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy = json.loads((brain / "scripts/ownership.json").read_text(encoding="utf-8"))

MEMBERS = [
    ("yassine", "traffic", "water"),
    ("meriem", "water", "emergency"),
    ("maram", "emergency", "traffic"),
]


@pytest.mark.parametrize("member,domain,other", MEMBERS)
def test_member_can_edit_complete_assigned_scenario(member, domain, other):
    paths = [
        f"brain/src/civis_brain/scenarios/{domain}/service.py",
        f"brain/tests/scenarios/{domain}/test_workflow.py",
        f"brain/mocks/cases/{domain}/base_case.json",
        f"brain/config/scenarios/{domain}.json",
        f"brain/docs/mock-team/progress/{member}.md",
    ]
    assert not module.validate(f"codex/civis-{member}", "codex/civis-elyes", paths, policy)


@pytest.mark.parametrize("member,domain,other", MEMBERS)
def test_member_cannot_change_core_other_scenario_or_prefix_lookalike(member, domain, other):
    forbidden = [
        "brain/src/civis_brain/contracts.py",
        "brain/src/civis_brain/scenarios/registry.py",
        "brain/src/civis_brain/planning/gemini.py",
        "brain/mocks/civis_mock_peers/peers.py",
        f"brain/src/civis_brain/scenarios/{other}/service.py",
        f"brain/config/scenarios/{other}.json",
        f"brain/src/civis_brain/scenarios/{domain}_other/service.py",
        f"brain/config/scenarios/{domain}.json.backup",
        ".github/workflows/civis-mock.yml",
        "guardian/src/service.py",
    ]
    for path in forbidden:
        assert module.validate(f"codex/civis-{member}", "codex/civis-elyes", [path], policy), path


@pytest.mark.parametrize("member,domain,other", MEMBERS)
def test_member_cannot_skip_integration_branch(member, domain, other):
    assert module.validate(f"codex/civis-{member}", "brain", [], policy)


def test_unknown_branch_is_rejected():
    assert module.validate("unassigned", "codex/civis-elyes", [], policy)


def test_leader_release_can_include_all_scenario_files():
    paths = ["brain/src/civis_brain/scenarios/water/service.py", ".github/workflows/civis-mock.yml"]
    assert not module.validate("codex/civis-elyes", "brain", paths, policy)
