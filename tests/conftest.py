"""Pytest-side safety net for the ambient-environment purge (#288).

Importing `_ambient_env` runs the purge. This file catches modules that forget the
import under pytest; `test_every_test_module_purges_the_ambient_environment` is
what catches them under `python3 -m unittest`, which never loads a conftest.
"""

import _ambient_env  # noqa: F401  (imported for its import-time purge)
