from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="module")
def isolated_ledger_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    home = tmp_path_factory.mktemp("deputy-home")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("HOME", str(home))
        yield
