import io
import zipfile

import pytest


def make_jar(members: dict) -> bytes:
    """Build an in-memory .jar (zip) with the given {name: text} members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def jar_factory(tmp_path):
    def _factory(filename: str, members: dict) -> str:
        path = tmp_path / filename
        path.write_bytes(make_jar(members))
        return str(path)
    return _factory
