#!/usr/bin/env python3
"""
Stealth Google Trends Downloader using Scrapling

Uses Scrapling's StealthyFetcher with patchright (patched Playwright) for
better anti-detection when scraping Google Trends. Reduces CAPTCHA triggers
and rate limiting compared to raw Selenium.

Features:
- Anti-fingerprinting (canvas noise, WebRTC blocking)
- Real Chrome browser support
- Connect to existing Chrome session via CDP
- Persistent browser profiles (cookies, sessions)
- Google referer spoofing

Usage:
    from trendspyg.stealth_downloader import download_google_trends_explore_stealth

    # Basic usage
    df = download_google_trends_explore_stealth(
        query="data governance",
        date_range="today 5-y",
        geo="US"
    )

    # Use your actual Chrome with existing session
    df = download_google_trends_explore_stealth(
        query="bitcoin",
        real_chrome=True,
        user_data_dir="~/.config/google-chrome/Default"
    )

    # Connect to Chrome running with --remote-debugging-port=9222
    df = download_google_trends_explore_stealth(
        query="ethereum",
        cdp_url="http://127.0.0.1:9222"
    )
"""

import os
import time
from typing import Optional, Any, Dict, List, Union, TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import pandas as pd
    from playwright.sync_api import Page

from .downloader import (
    OutputFormat,
    EXPLORE_CATEGORIES,
    EXPLORE_DATE_PRESETS,
    validate_geo,
    validate_date_range,
    validate_explore_category,
    parse_explore_csv,
)
from .exceptions import (
    InvalidParameterError,
    BrowserError,
    DownloadError,
)

# Check if scrapling is available
try:
    from scrapling.fetchers import StealthyFetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False


def _create_download_action(
    download_dir: str,
    timeout_ms: int = 30000
) -> Callable[['Page'], Optional[str]]:
    """Create a page_action function that clicks CSV download and captures the file.

    Uses Playwright's download event handling to properly capture downloads.

    Args:
        download_dir: Directory where downloads should be saved
        timeout_ms: Timeout in milliseconds

    Returns:
        Function that takes a Playwright page and returns downloaded file path
    """
    def download_action(page: 'Page') -> Optional[str]:
        """Click CSV download button and capture the download."""
        from datetime import datetime

        # Wait for page to fully load (AngularJS app)
        print("[INFO] Waiting for page content to load...")
        page.wait_for_timeout(5000)

        # Scroll down slightly to ensure chart is in view
        page.evaluate("window.scrollTo(0, 300)")
        page.wait_for_timeout(1000)

        # Try to find the CSV export button
        csv_selector = 'button.widget-actions-item.export[title="CSV"]'
        button_found = False

        try:
            page.wait_for_selector(csv_selector, timeout=10000)
            print("[OK] Found CSV export button")
            button_found = True
        except Exception:
            # Fallback selectors
            print("[WARN] Primary selector failed, trying fallbacks...")
            fallback_selectors = [
                '.widget-actions-item.export',
                'button[title="CSV"]',
                'button[ng-click="export()"]',
            ]
            for selector in fallback_selectors:
                try:
                    page.wait_for_selector(selector, timeout=3000)
                    csv_selector = selector
                    button_found = True
                    print(f"[OK] Found button with selector: {selector}")
                    break
                except Exception:
                    continue

        if not button_found:
            print("[ERROR] Could not find any export button")
            # Debug: check page content
            if 'unusual traffic' in page.content().lower():
                print("[ERROR] Detected 'unusual traffic' - CAPTCHA required")
            return None

        # Use Playwright's expect_download to capture the file
        print("[INFO] Clicking CSV export button and capturing download...")

        try:
            # Start waiting for download before clicking
            with page.expect_download(timeout=timeout_ms) as download_info:
                page.click(csv_selector)

            download = download_info.value

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            suggested_name = download.suggested_filename or "multiTimeline.csv"
            base_name = suggested_name.rsplit('.', 1)[0]
            final_name = f"{base_name}_{timestamp}.csv"
            final_path = os.path.join(download_dir, final_name)

            # Save to our download directory
            download.save_as(final_path)
            print(f"[OK] Downloaded: {final_name}")

            return final_path

        except Exception as e:
            print(f"[ERROR] Download failed: {type(e).__name__}: {e}")

            # Fallback: check if file appeared in default download location
            page.wait_for_timeout(5000)
            print("[INFO] Checking for file in download directory...")

            # Look for recently modified CSV files
            try:
                import glob
                csv_files = glob.glob(os.path.join(download_dir, "*.csv"))
                if csv_files:
                    newest = max(csv_files, key=os.path.getmtime)
                    # Check if it was modified in last 30 seconds
                    if time.time() - os.path.getmtime(newest) < 30:
                        print(f"[OK] Found recently downloaded: {os.path.basename(newest)}")
                        return newest
            except Exception:
                pass

            return None

    return download_action


def download_google_trends_explore_stealth(
    query: Union[str, List[str], None] = None,
    date_range: str = 'today 5-y',
    geo: str = 'US',
    category: Union[str, int, None] = None,
    hl: str = 'en-US',
    headless: bool = False,  # Default visible for manual CAPTCHA solving
    download_dir: Optional[str] = None,
    output_format: OutputFormat = 'dataframe',
    # Scrapling-specific options
    real_chrome: bool = False,
    cdp_url: Optional[str] = None,
    user_data_dir: Optional[str] = None,
    hide_canvas: bool = True,
    block_webrtc: bool = True,
    timeout: int = 60000,
) -> Union[Dict[str, Any], 'pd.DataFrame', str, None]:
    """
    Download Google Trends explore data using Scrapling's stealth browser.

    This version uses patchright (patched Playwright) with anti-detection
    features to reduce CAPTCHA triggers and rate limiting.

    Args:
        query: Search term(s) to analyze. Up to 5 terms for comparison.
        date_range: Time period. Presets: 'today 5-y', 'today 12-m', etc.
        geo: Country code (US, HK, GB, etc.)
        category: Category filter (name or ID). See EXPLORE_CATEGORIES.
        hl: Language code for results
        headless: Run browser in headless mode (default False for CAPTCHA solving)
        download_dir: Directory for CSV files
        output_format: 'dataframe', 'csv', or 'json'

        # Stealth options:
        real_chrome: Use your installed Chrome browser (better fingerprint)
        cdp_url: Connect to existing Chrome via CDP (e.g., "http://127.0.0.1:9222")
                 Start Chrome with: google-chrome --remote-debugging-port=9222
        user_data_dir: Path to Chrome user data directory for persistent sessions
                       (e.g., "~/.config/google-chrome/Default")
        hide_canvas: Add noise to canvas fingerprinting (default True)
        block_webrtc: Block WebRTC to prevent IP leak (default True)
        timeout: Timeout in milliseconds (default 60000)

    Returns:
        DataFrame of interest over time, CSV path, or parsed dict

    Example:
        # Basic usage with stealth
        df = download_google_trends_explore_stealth(
            query="artificial intelligence",
            date_range="today 5-y"
        )

        # Connect to your running Chrome session (best for avoiding CAPTCHA)
        # First: google-chrome --remote-debugging-port=9222
        df = download_google_trends_explore_stealth(
            query="bitcoin",
            cdp_url="http://127.0.0.1:9222"
        )

        # Use your Chrome with persistent profile
        df = download_google_trends_explore_stealth(
            query="ethereum",
            real_chrome=True,
            user_data_dir="~/.config/google-chrome"
        )
    """
    if not SCRAPLING_AVAILABLE:
        raise ImportError(
            "scrapling is required for stealth mode.\n"
            "Install with: pip install scrapling[all]\n"
            "Then run: scrapling install"
        )

    # Validate parameters
    geo = validate_geo(geo)
    date_range = validate_date_range(date_range)
    cat_id = validate_explore_category(category)

    # Normalize query to list
    if query is None:
        queries = []
    elif isinstance(query, str):
        queries = [query]
    else:
        queries = list(query)

    if len(queries) > 5:
        raise InvalidParameterError("Maximum 5 queries allowed for comparison")

    if not queries and not cat_id:
        raise InvalidParameterError(
            "Either query or category must be specified.\n"
            "Use query='search term' or category='finance' (etc.)"
        )

    # Setup download directory
    if download_dir is None:
        download_dir = os.path.join(os.getcwd(), 'downloads')
    download_dir = os.path.abspath(os.path.expanduser(download_dir))
    os.makedirs(download_dir, exist_ok=True)

    # Expand user_data_dir if provided
    if user_data_dir:
        user_data_dir = os.path.expanduser(user_data_dir)

    # Build URL
    from urllib.parse import quote
    date_encoded = date_range.replace(' ', '%20')
    url = f"https://trends.google.com/trends/explore?date={date_encoded}&geo={geo}&hl={hl}"

    if queries:
        q_encoded = ','.join(quote(q) for q in queries)
        url += f"&q={q_encoded}"

    if cat_id:
        url += f"&cat={cat_id}"

    print(f"[INFO] Opening Google Trends Explore (stealth mode)...")
    print(f"       Query: {queries if queries else '(category browse)'}")
    print(f"       Date range: {date_range}")
    print(f"       Location: {geo}")
    print(f"       URL: {url}")
    if cdp_url:
        print(f"       CDP: {cdp_url}")
    if real_chrome:
        print(f"       Using: Real Chrome")
    if user_data_dir:
        print(f"       Profile: {user_data_dir}")

    # Create download action
    download_action = _create_download_action(download_dir, timeout)

    # Track downloaded file path
    csv_path = None

    def combined_action(page: 'Page') -> None:
        """Combined action that stores result in outer scope."""
        nonlocal csv_path
        csv_path = download_action(page)

    try:
        # Build kwargs, excluding None values (Scrapling doesn't accept None)
        fetch_kwargs = {
            'url': url,
            'headless': headless,
            'hide_canvas': hide_canvas,
            'block_webrtc': block_webrtc,
            'google_search': True,  # Referer from Google search
            'network_idle': True,
            'timeout': timeout,
            'page_action': combined_action,
            'disable_resources': False,  # Need full page for charts
        }

        # Only add optional params if they have values
        if real_chrome:
            fetch_kwargs['real_chrome'] = real_chrome
        if cdp_url:
            fetch_kwargs['cdp_url'] = cdp_url
        if user_data_dir:
            fetch_kwargs['user_data_dir'] = user_data_dir

        # Fetch with StealthyFetcher
        response = StealthyFetcher.fetch(**fetch_kwargs)

        print(f"[INFO] Page status: {response.status}")

    except Exception as e:
        raise BrowserError(f"Stealth browser error: {type(e).__name__}: {e}")

    # Check if download succeeded
    if not csv_path:
        # Try checking download dir one more time for recent files
        time.sleep(2)
        try:
            import glob
            csv_files = glob.glob(os.path.join(download_dir, "*.csv"))
            if csv_files:
                newest = max(csv_files, key=os.path.getmtime)
                # Check if modified in last 60 seconds
                if time.time() - os.path.getmtime(newest) < 60:
                    csv_path = newest
                    print(f"[OK] Downloaded (delayed detection): {os.path.basename(newest)}")
        except Exception:
            pass

        if not csv_path:
            raise DownloadError(
                "Download failed - no CSV file detected.\n\n"
                "Possible causes:\n"
                "- CAPTCHA appeared and wasn't solved\n"
                "- Rate limiting (429)\n"
                "- Page structure changed\n\n"
                "Try:\n"
                "- Run with headless=False to see what's happening\n"
                "- Use cdp_url to connect to your running Chrome\n"
                "- Add delays between requests"
            )

    # Return based on format
    if output_format == 'csv':
        return csv_path

    # Parse the CSV
    parsed = parse_explore_csv(csv_path)

    if output_format == 'dataframe':
        if parsed['interest_over_time'] is not None:
            return parsed['interest_over_time']
        else:
            print("[WARN] No interest_over_time data found, returning empty DataFrame")
            import pandas as pd
            return pd.DataFrame()

    # json format - return full parsed dict
    return parsed


# Re-export constants for convenience
__all__ = [
    'download_google_trends_explore_stealth',
    'EXPLORE_CATEGORIES',
    'EXPLORE_DATE_PRESETS',
    'SCRAPLING_AVAILABLE',
]
