"""Alias test module so both `test_00_foundation.py` and `test_00_contracts_and_security.py` run Plan 00 tests."""

from __future__ import annotations

import unittest
from tests.test_00_contracts_and_security import TestPlan00ContractsAndSecurity

__all__ = ["TestPlan00ContractsAndSecurity"]

if __name__ == "__main__":
    unittest.main(verbosity=2)
