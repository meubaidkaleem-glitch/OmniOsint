"""Filesystem locations used by OmniOSINT.

Program files (this package, the default configuration, the built web
interface) and user data (settings, logs, backups, secrets) are deliberately
kept apart so that updating or removing the program never touches user data.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "OmniOSINT"
HOME_ENV = "OMNIOSINT_HOME"
ROOT_ENV = "OMNIOSINT_ROOT"

_PACKAGE_DIR = Path(__file__).resolve().parent.parent


@cache
def project_root() -> Path | None:
    """Return the source checkout this package runs from, if any.

    ``None`` means the package was installed as a wheel and there is no
    surrounding project directory.
    """
    override = os.environ.get(ROOT_ENV)
    if override:
        candidate = Path(override).expanduser().resolve()
        return candidate if candidate.is_dir() else None
    for parent in _PACKAGE_DIR.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    return None


def default_config_dir() -> Path:
    """Directory holding the shipped default configuration files."""
    root = project_root()
    if root is not None:
        return root / "config"
    return _PACKAGE_DIR / "_default_config"


def default_frontend_dist() -> Path | None:
    """Location of the built web interface, when it can be inferred."""
    root = project_root()
    if root is not None:
        return root / "frontend" / "dist"
    packaged = _PACKAGE_DIR / "_frontend"
    return packaged if packaged.is_dir() else None


def resolve_home() -> Path:
    """Return the data directory: ``OMNIOSINT_HOME`` or the per-user default."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir(APP_NAME, appauthor=False, roaming=False))


@dataclass(frozen=True, slots=True)
class AppPaths:
    """All per-user locations, derived from one home directory."""

    home: Path

    @classmethod
    def resolve(cls, home: Path | None = None) -> AppPaths:
        return cls(home=(home or resolve_home()))

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def user_settings_file(self) -> Path:
        return self.config_dir / "settings.yaml"

    @property
    def env_file(self) -> Path:
        return self.home / ".env"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def run_dir(self) -> Path:
        return self.home / "run"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def secrets_dir(self) -> Path:
        return self.home / "secrets"

    @property
    def setup_token_file(self) -> Path:
        return self.home / "setup-token.txt"

    @property
    def install_file(self) -> Path:
        return self.home / "install.json"

    def all_dirs(self) -> tuple[Path, ...]:
        return (
            self.home,
            self.config_dir,
            self.data_dir,
            self.storage_dir,
            self.logs_dir,
            self.run_dir,
            self.backups_dir,
            self.secrets_dir,
        )

    def ensure(self) -> None:
        """Create the directory tree with owner-only permissions where supported."""
        for directory in self.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)
            restrict_to_owner(directory)


def restrict_to_owner(path: Path) -> None:
    """Limit ``path`` to its owner.

    On POSIX this sets mode 0700/0600. On Windows the per-user profile
    directory already carries an ACL limited to the user, SYSTEM and
    Administrators, and ``chmod`` cannot express more, so nothing is done.
    """
    if sys.platform == "win32":
        return
    mode = 0o700 if path.is_dir() else 0o600
    try:
        path.chmod(mode)
    except OSError:
        # A read-only or foreign-owned location; the doctor command reports it.
        pass


def is_owner_only(path: Path) -> bool | None:
    """Whether ``path`` is private to its owner; ``None`` when not checkable."""
    if sys.platform == "win32":
        return None
    try:
        return (path.stat().st_mode & 0o077) == 0
    except OSError:
        return None


def write_private_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` so that only the owner can read it.

    The file is created with restrictive permissions from the start rather than
    tightened afterwards, and replaced atomically.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    restrict_to_owner(path)
