"""Replay portable fuzz seeds with no Atheris dependency."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

FUZZ = Path(__file__).parents[1] / "fuzz"


@pytest.mark.parametrize("seed", sorted((FUZZ / "corpus").iterdir()), ids=lambda p: p.name)
def test_fuzz_seed(seed):
    spec = spec_from_file_location("fuzz_target", FUZZ / "remote_selection.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_input(seed.read_bytes())
