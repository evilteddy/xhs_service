"""
Browser control and login management module for Xiaohongshu crawler.
Uses DrissionPage to automate Chromium-based browser interactions.

Key design:
  - Uses a FIXED debugging port so every run reconnects to the same browser.
  - Persists user-data (cookies / session) in a local directory.
  - After crawling, only *disconnects* from the browser — does NOT close it.
    This keeps the login session alive across multiple runs.

@author jinbiao.sun
"""

import os
import time
import logging

from DrissionPage import Chromium, ChromiumOptions
from DrissionPage.errors import BrowserConnectError

logger = logging.getLogger(__name__)

XHS_HOME_URL = "https://www.xiaohongshu.com"

# Fixed port for remote-debugging — allows reconnecting to the same browser
DEFAULT_DEBUG_PORT = 9515
# Directory to persist cookies / login session
DEFAULT_USER_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'browser_data',
)


class BrowserManager:
    """
    Manages a Chromium browser instance for crawling Xiaohongshu.

    The browser runs on a fixed debugging port so that:
      1. If an existing browser is already open → we reconnect to it.
      2. If no browser is found → a new one is launched.
    After crawling, `disconnect()` releases the Python-side reference but
    leaves the browser running so the login session persists.
    """

    def __init__(
        self,
        login_wait: int = 20,
        debug_port: int = DEFAULT_DEBUG_PORT,
        user_data_dir: str = DEFAULT_USER_DATA_DIR,
    ):
        """
        Initialize the BrowserManager.

        Args:
            login_wait: Seconds to wait for QR code login on first run.
            debug_port: Fixed Chrome remote-debugging port.
            user_data_dir: Directory to persist browser profile data.
        """
        self._browser: Chromium | None = None
        self._page = None
        self._login_wait = login_wait
        self._debug_port = debug_port
        self._user_data_dir = user_data_dir

    def _build_options(self) -> ChromiumOptions:
        """Build ChromiumOptions with fixed port and persistent user data."""
        co = ChromiumOptions()
        co.set_local_port(self._debug_port)
        co.set_user_data_path(self._user_data_dir)
        # Common anti-detection flags
        co.set_argument('--disable-blink-features=AutomationControlled')
        return co

    def _get_browser(self) -> Chromium:
        """
        Get or create a Chromium browser instance.

        If a browser is already running on the configured port, connect to it.
        Otherwise, launch a new browser.
        """
        if self._browser is not None:
            return self._browser

        co = self._build_options()

        try:
            logger.info(
                f"Connecting to browser on port {self._debug_port}..."
            )
            self._browser = Chromium(co)
            logger.info("Browser connected successfully.")
        except BrowserConnectError:
            logger.info(
                "No existing browser found. Launching a new one..."
            )
            self._browser = Chromium(co)

        return self._browser

    @property
    def page(self):
        """Return the current page (tab), creating a browser if needed."""
        if self._page is None:
            browser = self._get_browser()
            self._page = browser.latest_tab
        return self._page

    # ----- Login -----

    def login(self) -> None:
        """
        Open Xiaohongshu home page and wait for user to scan QR code.
        Only needed on the first run; afterwards the session is persisted
        in the browser profile directory.
        """
        logger.info("Opening Xiaohongshu home page for login...")
        self.page.get(XHS_HOME_URL)
        logger.info(
            f"Please scan the QR code to log in within {self._login_wait} seconds."
        )
        time.sleep(self._login_wait)
        if self.is_logged_in():
            logger.info("Login successful! Session will persist across runs.")
        else:
            logger.warning(
                "Login may not have completed. "
                "Please verify manually and re-run if needed."
            )

    def is_logged_in(self) -> bool:
        """
        Check whether the user is currently logged in.

        Returns:
            True if logged in, False otherwise.
        """
        try:
            login_indicator = self.page.ele('.user-info', timeout=3)
            return login_indicator is not None
        except Exception:
            try:
                login_btn = self.page.ele('.login-btn', timeout=2)
                return login_btn is None
            except Exception:
                return False

    # ----- Navigation -----

    def navigate(self, url: str) -> None:
        """
        Navigate the browser to the specified URL.

        Args:
            url: Target URL.
        """
        logger.debug(f"Navigating to: {url}")
        self.page.get(url)

    def scroll_to_bottom(self) -> None:
        """Scroll the current page to the bottom to trigger lazy loading."""
        self.page.scroll.to_bottom()

    # ----- Reconnection -----

    def reconnect(self) -> None:
        """
        Reset internal references and reconnect to the browser.
        Used when the page connection is lost mid-crawl (e.g. browser
        tab crashed or DevTools socket dropped).
        """
        logger.info("Attempting to reconnect to browser...")
        self._page = None
        self._browser = None
        try:
            browser = self._get_browser()
            self._page = browser.latest_tab
            logger.info("Browser reconnected successfully.")
        except Exception as e:
            logger.error(f"Failed to reconnect to browser: {e}")
            raise

    # ----- Lifecycle -----

    def disconnect(self) -> None:
        """
        Disconnect from the browser WITHOUT closing it.
        The browser keeps running in the background so the login session
        persists for the next crawl run.
        """
        logger.info(
            "Disconnecting from browser (browser stays open for session reuse)."
        )
        self._page = None
        self._browser = None

    def close(self) -> None:
        """
        Actually close / quit the browser process.
        Use this only when you explicitly want to end the browser.
        """
        if self._browser is not None:
            try:
                logger.info("Closing browser...")
                self._browser.quit()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self._browser = None
                self._page = None
        else:
            logger.info("No browser to close.")
