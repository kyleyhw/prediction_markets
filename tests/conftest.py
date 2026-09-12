"""Shared fixtures. The seed is drawn by NumPy, never hard-coded, and printed so
a failing run can be reproduced."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="session")
def seed() -> int:
    value = int(np.random.default_rng().integers(2**32))
    print(f"\nrandom seed for this session: {value}")
    return value
