import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("ownership", Path(__file__).parents[1] / "scripts/check_ownership.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy = {
    "integration_branch": "codex/civis-elyes",
    "branches": {"codex/civis-yassine": ["brain/src/civis_brain/inputs/"],
                 "codex/civis-elyes": ["brain/"]},
}


def test_member_cannot_change_shared_contracts():
    errors = module.validate("codex/civis-yassine", "codex/civis-elyes",
                             ["brain/src/civis_brain/contracts.py"], policy)
    assert errors


def test_member_cannot_skip_integration_branch():
    assert module.validate("codex/civis-yassine", "brain", [], policy)


def test_member_can_edit_own_module():
    assert not module.validate("codex/civis-yassine", "codex/civis-elyes",
                               ["brain/src/civis_brain/inputs/service.py"], policy)
