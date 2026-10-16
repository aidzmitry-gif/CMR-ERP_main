import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def tmp_path():
    # Same Windows sandbox convention as tests/conftest.py, without loading the ERP DB.
    path = Path(".tmp_pytest/eschf") / uuid4().hex
    path.mkdir(parents=True)
    return path
