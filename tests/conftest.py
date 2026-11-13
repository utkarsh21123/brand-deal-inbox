import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def profile():
    return json.loads((DATA / "creator_profile.json").read_text())


@pytest.fixture(scope="session")
def inbox():
    return {e["id"]: e for e in json.loads((DATA / "inbox.json").read_text())}
