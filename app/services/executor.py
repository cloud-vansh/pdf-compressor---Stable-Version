"""
app/services/executor.py
Safe subprocess runner, OS detection, and dependency availability checks.
Required pipeline tools: pdftoppm, mogrify (ImageMagick), img2pdf (Python package).
"""

from __future__ import annotations

import importlib.util
import logging
import platform
import shutil
import subprocess

logger = logging.getLogger(__name__)


# ── OS detection ──────────────────────────────────────────────────────────────

def current_os() -> str:
    """Return 'Windows', 'Linux', or 'Darwin'."""
    return platform.system()


def is_windows() -> bool:
    return current_os() == "Windows"


# ── Command runner ────────────────────────────────────────────────────────────

def run_command(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 300,
) -> tuple[int, str, str]:
    """
    Execute *cmd* and return (returncode, stdout, stderr).
    Never raises; all errors are surfaced via return code -1 and stderr string.
    """
    logger.debug("CMD: %s", " ".join(str(c) for c in cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        if result.returncode != 0:
            logger.warning(
                "Exit %d | cmd=%s | stderr=%s",
                result.returncode,
                cmd[0],
                result.stderr.strip()[:200],
            )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Timeout (%ds): %s", timeout, cmd[0])
        return -1, "", f"Command timed out after {timeout}s."
    except FileNotFoundError:
        logger.error("Not found: %s", cmd[0])
        return -1, "", f"Executable not found: {cmd[0]}"
    except OSError as exc:
        logger.error("OS error running %s: %s", cmd[0], exc)
        return -1, "", f"OS error: {exc}"


# ── Dependency checks ─────────────────────────────────────────────────────────

def check_dependencies() -> dict[str, bool]:
    """
    Return availability of all required pipeline tools.

    Keys: 'pdftoppm', 'mogrify', 'img2pdf'
    """
    deps: dict[str, bool] = {}

    # System binaries
    for tool in ("pdftoppm", "mogrify"):
        deps[tool] = shutil.which(tool) is not None
        logger.info("%-12s %s", tool, "OK" if deps[tool] else "MISSING")

    # img2pdf is a Python package — instant importlib check (no subprocess spawn)
    deps["img2pdf"] = importlib.util.find_spec("img2pdf") is not None
    logger.info("%-12s %s", "img2pdf", "OK" if deps["img2pdf"] else "MISSING")

    return deps


def install_hint(tool: str) -> str:
    """Return a platform-appropriate install instruction for a missing tool."""
    os_name = current_os()

    hints: dict[str, dict[str, str]] = {
        "pdftoppm": {
            "Linux":   "sudo apt install poppler-utils    (Debian/Ubuntu)\n"
                       "sudo dnf install poppler-utils    (Fedora)",
            "Darwin":  "brew install poppler",
            "Windows": "Download from: https://github.com/oschwartz10612/poppler-windows/releases\n"
                       "Extract and add the bin/ folder to your system PATH.",
        },
        "mogrify": {
            "Linux":   "sudo apt install imagemagick      (Debian/Ubuntu)\n"
                       "sudo dnf install ImageMagick      (Fedora)",
            "Darwin":  "brew install imagemagick",
            "Windows": "Download from: https://imagemagick.org/script/download.php#windows\n"
                       "Use the installer and ensure 'Add to PATH' is checked.",
        },
        "img2pdf": {
            "Linux":   "pip install img2pdf",
            "Darwin":  "pip install img2pdf",
            "Windows": "pip install img2pdf",
        },
    }

    tool_hints = hints.get(tool, {})
    return tool_hints.get(os_name, tool_hints.get("Linux", "See project documentation."))


def get_tool_version(tool: str) -> str:
    """Return version string for a binary, or 'not found'."""
    rc, stdout, stderr = run_command([tool, "--version"])
    if rc == 0:
        return (stdout or stderr).split("\n")[0].strip()
    return "not found"
