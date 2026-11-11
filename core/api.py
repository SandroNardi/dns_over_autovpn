import os
import re

import meraki

from .logger import logger

# Dashboard API keys are 40 hexadecimal characters. Anything else is refused
# before a session is created, and the rejected value is not logged.
_KEY_SHAPE = re.compile(r"[0-9a-fA-F]{40}")

ALLOWED_SECTIONS = ("organizations", "appliance", "switch")


class _ReadOnlySection:
    def __init__(self, section, name):
        self._section = section
        self._name = name

    def __getattr__(self, attr):
        if not attr.startswith("get"):
            raise PermissionError(f"{self._name}.{attr} is blocked. This tool only reads the Dashboard.")
        return getattr(self._section, attr)


class ReadOnlyDashboard:
    """Expose only get* methods of the Dashboard sections this tool reads."""

    def __init__(self, api):
        self._api = api

    def __getattr__(self, name):
        if name not in ALLOWED_SECTIONS:
            raise PermissionError(f"{name} is blocked. This tool only reads the Dashboard.")
        return _ReadOnlySection(getattr(self._api, name), name)


def _dashboard(api_key):
    """Build a read-only client. The key stays inside that client and is not logged."""
    return ReadOnlyDashboard(
        meraki.DashboardAPI(
            api_key=api_key,
            suppress_logging=True,
            print_console=False,
            output_log=False,
            maximum_retries=5,
        )
    )


class MerakiSession:
    """Dashboard session.

    The key comes from MK_CSM_KEY, or from one paste accepted by the local page.
    A pasted key is held in this process only. It is not written to the
    environment, a file, or the log.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.api = None
            cls._instance.from_paste = False
        return cls._instance

    def configured(self):
        return self.api is not None or bool(os.getenv("MK_CSM_KEY"))

    def get_dashboard(self):
        if self.api is None:
            api_key = os.getenv("MK_CSM_KEY")
            if not api_key:
                logger.error("No Dashboard API key is available.")
                raise EnvironmentError(
                    "No Dashboard API key is available. Set MK_CSM_KEY, or paste a key in the page."
                )
            self.api = _dashboard(api_key)
            self.from_paste = False
            logger.info("[bold green]Meraki Dashboard session started from the environment (read only).[/]")
        return self.api

    def use_key(self, api_key):
        """Accept one pasted key. Raises ValueError when the value is unusable."""
        if self.api is not None or os.getenv("MK_CSM_KEY"):
            raise RuntimeError("A Dashboard API key is already in use.")
        key = str(api_key or "").strip()
        if not _KEY_SHAPE.fullmatch(key):
            raise ValueError("unusable key")
        self.api = _dashboard(key)
        self.from_paste = True
        logger.info("[bold green]Dashboard API key accepted for this process only (read only).[/]")

    def forget(self):
        """Drop a pasted key. Used when the process should not keep one, and by tests."""
        self.api = None
        self.from_paste = False


session = MerakiSession()
