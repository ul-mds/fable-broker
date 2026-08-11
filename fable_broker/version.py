import tomllib
from pathlib import Path


def _get_version():
    pyproject_toml = Path(__file__).parent.parent / "pyproject.toml"

    with open(pyproject_toml, mode="rb") as f:
        content = tomllib.load(f)

    return content["project"]["version"]


__version__ = _get_version()
