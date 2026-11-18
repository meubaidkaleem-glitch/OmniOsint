"""Static checks of the Windows scripts.

PowerShell cannot run in the Linux test environment, so these tests guard the
mistakes that are easy to make and expensive to find on Windows: a CI run of
``install.bat -NonInteractive`` once waited six hours at a password prompt
because ``common.ps1`` (dot-sourced into the caller's scope) reset a variable
with the same name as the caller's ``-NonInteractive`` switch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "scripts" / "windows"
COMMON = WINDOWS / "common.ps1"
POWERSHELL_SCRIPTS = sorted([ROOT / "setup.ps1", *WINDOWS.glob("*.ps1")])
ALL_SCRIPTS = sorted(
    [*POWERSHELL_SCRIPTS, *ROOT.glob("*.bat"), *WINDOWS.glob("*.cmd"), *WINDOWS.glob("*.bat")]
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _param_names(text: str) -> set[str]:
    match = re.search(r"(?ms)^param\((.*?)^\)", text)
    if not match:
        return set()
    return {name.lower() for name in re.findall(r"\$(\w+)", match.group(1))}


def _functions(text: str) -> dict[str, str]:
    """Function name to body, for the top-level functions of a script."""
    bodies: dict[str, str] = {}
    for match in re.finditer(r"(?m)^function\s+([\w-]+)", text):
        start = text.index("{", match.end())
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    bodies[match.group(1)] = text[start : index + 1]
                    break
    return bodies


def test_the_scripts_exist() -> None:
    names = {path.name for path in ALL_SCRIPTS}
    for required in (
        "install.bat",
        "setup.ps1",
        "start.bat",
        "stop.bat",
        "restart.bat",
        "health-check.bat",
        "update.bat",
        "backup.bat",
        "restore.bat",
        "uninstall.bat",
        "common.ps1",
    ):
        assert required in names


@pytest.mark.parametrize("path", ALL_SCRIPTS, ids=_relative)
def test_scripts_are_ascii(path: Path) -> None:
    # Windows PowerShell 5.1 reads a script without a byte-order mark in the
    # system code page; anything outside ASCII may be garbled.
    data = path.read_bytes()
    assert data.isascii(), f"{_relative(path)} contains non-ASCII bytes"


@pytest.mark.parametrize("path", [p for p in POWERSHELL_SCRIPTS if p != COMMON], ids=_relative)
def test_parameters_do_not_collide_with_common_variables(path: Path) -> None:
    common_variables = {
        name.lower()
        for name in re.findall(r"(?m)^\$script:(\w+)\s*=", COMMON.read_text(encoding="ascii"))
    }
    assert common_variables, "expected script variables in common.ps1"
    text = path.read_text(encoding="ascii")
    assert "common.ps1" in text
    collisions = _param_names(text) & common_variables
    assert not collisions, (
        f"{_relative(path)} has parameters {sorted(collisions)} that common.ps1 overwrites "
        "when it is dot-sourced"
    )


def test_prompts_in_common_helpers_respect_non_interactive_mode() -> None:
    functions = _functions(COMMON.read_text(encoding="ascii"))
    prompting = {name: body for name, body in functions.items() if "Read-Host" in body}
    assert {"Read-YesNo", "Read-Choice", "Read-Value", "Read-Secret"} <= set(prompting)
    for name, body in prompting.items():
        assert "$script:OmniNonInteractive" in body, f"{name} prompts even when non-interactive"


@pytest.mark.parametrize("path", [p for p in POWERSHELL_SCRIPTS if p != COMMON], ids=_relative)
def test_direct_prompts_are_guarded(path: Path) -> None:
    lines = path.read_text(encoding="ascii").splitlines()
    for number, line in enumerate(lines):
        if "Read-Host" not in line:
            continue
        context = "\n".join(lines[max(0, number - 4) : number])
        assert "-not $Yes" in context or "OmniNonInteractive" in context, (
            f"{_relative(path)}:{number + 1} prompts without a non-interactive guard"
        )
