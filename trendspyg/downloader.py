#!/usr/bin/env python3
"""
Configurable Google Trends CSV Downloader
Download trends with custom filters: location, time period, category, sort, etc.

Usage Examples:
    # Download US trends from past 24 hours
    py download_trends_configurable.py

    # Download Canada trends from past 4 hours, Sports only
    py download_trends_configurable.py --geo CA --hours 4 --category sports

    # Download UK trends from past 7 days, sorted by search volume
    py download_trends_configurable.py --geo UK --hours 168 --sort volume
"""

import os
import time
import argparse
from typing import Optional, Callable, Any, Dict, Set, List, Literal, Union, TYPE_CHECKING
from selenium import webdriver

if TYPE_CHECKING:
    import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    ElementClickInterceptedException
)
from datetime import datetime

# Import config and exceptions
from .config import COUNTRIES, US_STATES
from .exceptions import (
    InvalidParameterError,
    BrowserError,
    DownloadError
)

# Type aliases
OutputFormat = Literal['csv', 'json', 'parquet', 'dataframe']
SortOption = Literal['relevance', 'title', 'volume', 'recency']


# Category mapping (numeric IDs for Google Trends /trending page)
# URL format: https://trends.google.com/trending?geo=US&category=18
# NOTE: These IDs are specific to the /trending page, NOT the same as pytrends API categories
CATEGORIES: Dict[str, str] = {
    'all': '',
    'business': '3',         # Business & Finance
    'health': '7',           # Health
    'law': '10',             # Law & Government
    'politics': '14',        # Politics
    'technology': '18',      # Technology
    'science': '20',         # Science
    # Aliases for convenience
    'tech': '18',            # Alias for technology
    'gov': '10',             # Alias for law & government
    'government': '10',      # Alias for law & government
}

# Time period options (in hours)
TIME_PERIODS: Dict[str, int] = {
    '4h': 4,
    '24h': 24,
    '48h': 48,
    '7d': 168  # 7 days = 168 hours
}

# Sort options
SORT_OPTIONS: List[str] = ['relevance', 'title', 'volume', 'recency']

# ============================================================================
# EXPLORE ENDPOINT CONSTANTS (different from /trending)
# ============================================================================

# Category IDs for /trends/explore (pytrends-style, different from /trending!)
# Full list: https://github.com/pat310/google-trends-api/wiki/Google-Trends-Categories
EXPLORE_CATEGORIES: Dict[str, int] = {
    'all': 0,
    'arts_entertainment': 3,
    'autos_vehicles': 47,
    'beauty_fitness': 44,
    'books_literature': 22,
    'business_industrial': 12,
    'computers_electronics': 5,
    'finance': 7,
    'food_drink': 71,
    'games': 8,
    'health': 45,
    'hobbies_leisure': 65,
    'home_garden': 11,
    'internet_telecom': 13,
    'jobs_education': 958,
    'law_government': 19,
    'news': 16,
    'online_communities': 299,
    'people_society': 14,
    'pets_animals': 66,
    'real_estate': 29,
    'reference': 533,
    'science': 174,
    'shopping': 18,
    'sports': 20,
    'travel': 67,
    # Useful subcategories for Long View
    'ai_ml': 1299,              # Machine Learning & AI
    'computer_security': 314,   # Cybersecurity
    'investing': 107,
    'politics': 396,
    'banking': 37,
    'accounting': 278,
}

# Date range presets for explore endpoint
EXPLORE_DATE_PRESETS: List[str] = [
    'today 5-y',   # Past 5 years (weekly data)
    'today 12-m',  # Past 12 months (weekly data)
    'today 3-m',   # Past 3 months (daily data)
    'today 1-m',   # Past 1 month (daily data)
    'now 7-d',     # Past 7 days (hourly data)
    'now 1-d',     # Past 24 hours (minute data)
]


def _download_with_retry(download_func: Callable[[], Any], max_retries: int = 3) -> Any:
    """Wrapper to retry download with exponential backoff.

    Args:
        download_func: Function to call for download
        max_retries: Maximum number of retry attempts

    Returns:
        Result of download_func

    Raises:
        Last exception if all retries fail
    """
    for attempt in range(max_retries):
        try:
            return download_func()
        except (BrowserError, DownloadError, TimeoutException) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"[WARN] Attempt {attempt + 1} failed: {type(e).__name__}")
                print(f"[INFO] Retrying in {wait_time}s... ({attempt + 2}/{max_retries})")
                time.sleep(wait_time)
            else:
                # Last attempt failed, re-raise
                print(f"[ERROR] All {max_retries} attempts failed")
                raise


def validate_geo(geo: str) -> str:
    """Validate geo parameter against available countries and US states.

    Args:
        geo: Country or US state code

    Raises:
        InvalidParameterError: If geo code is invalid

    Returns:
        Validated geo code (uppercased)
    """
    geo = geo.upper()

    if geo in COUNTRIES or geo in US_STATES:
        return geo

    # Try to find similar matches for helpful error message
    similar = [code for code in list(COUNTRIES.keys()) + list(US_STATES.keys())
               if len(geo) > 0 and code.startswith(geo[0])][:5]

    error_msg = f"Invalid geo code '{geo}'."
    if similar:
        error_msg += f" Did you mean one of: {', '.join(similar)}?"
    error_msg += f"\n\nAvailable: {len(COUNTRIES)} countries (US, CA, UK, DE, FR, ...) "
    error_msg += f"or {len(US_STATES)} US states (CA, NY, TX, FL, ...)"
    error_msg += "\n\nSee trendspyg.config.COUNTRIES and trendspyg.config.US_STATES for full list."

    raise InvalidParameterError(error_msg)


def validate_hours(hours: int) -> int:
    """Validate hours parameter against available time periods.

    Args:
        hours: Time period in hours

    Raises:
        InvalidParameterError: If hours value is invalid

    Returns:
        Validated hours value
    """
    valid_hours = [4, 24, 48, 168]

    if hours in valid_hours:
        return hours

    raise InvalidParameterError(
        f"Invalid hours value '{hours}'. Must be one of: {valid_hours}\n"
        f"  4   = Past 4 hours\n"
        f"  24  = Past 24 hours (1 day)\n"
        f"  48  = Past 48 hours (2 days)\n"
        f"  168 = Past 168 hours (7 days)"
    )


def validate_category(category: str) -> str:
    """Validate category parameter against available categories.

    Args:
        category: Category name

    Raises:
        InvalidParameterError: If category is invalid

    Returns:
        Validated category (lowercased)
    """
    category = category.lower()

    if category in CATEGORIES:
        return category

    # Try to find similar matches
    similar = [cat for cat in CATEGORIES.keys() if cat.startswith(category[:3]) if len(category) >= 3][:5]

    error_msg = f"Invalid category '{category}'."
    if similar:
        error_msg += f" Did you mean one of: {', '.join(similar)}?"
    error_msg += f"\n\nAvailable categories: {', '.join(sorted(CATEGORIES.keys()))}"

    raise InvalidParameterError(error_msg)


def _convert_csv_to_format(
    csv_path: str,
    output_format: OutputFormat,
    download_dir: str
) -> Union[str, 'pd.DataFrame']:
    """Convert downloaded CSV to requested output format.

    Args:
        csv_path: Path to the downloaded CSV file
        output_format: Desired output format
        download_dir: Directory for output files

    Returns:
        Path to converted file or DataFrame object

    Raises:
        ImportError: If required library is not installed
        DownloadError: If conversion fails
    """
    if output_format == 'csv':
        return csv_path

    # Import pandas for all non-CSV formats
    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            f"pandas is required for '{output_format}' format.\n"
            "Install with: pip install trendspyg[analysis]"
        )

    # Read CSV
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        raise DownloadError(f"Failed to read CSV file: {e}")

    # Return DataFrame directly if requested
    if output_format == 'dataframe':
        return df

    # Convert to other formats
    base_path = csv_path.rsplit('.', 1)[0]  # Remove .csv extension

    if output_format == 'json':
        json_path = base_path + '.json'
        try:
            df.to_json(json_path, orient='records', indent=2)
            # Remove original CSV
            os.remove(csv_path)
            print(f"[OK] Converted to JSON: {os.path.basename(json_path)}")
            return json_path
        except Exception as e:
            raise DownloadError(f"Failed to convert to JSON: {e}")

    elif output_format == 'parquet':
        parquet_path = base_path + '.parquet'
        try:
            df.to_parquet(parquet_path, index=False)
            # Remove original CSV
            os.remove(csv_path)
            print(f"[OK] Converted to Parquet: {os.path.basename(parquet_path)}")
            return parquet_path
        except ImportError:
            raise ImportError(
                "pyarrow is required for parquet format.\n"
                "Install with: pip install pyarrow"
            )
        except Exception as e:
            raise DownloadError(f"Failed to convert to Parquet: {e}")

    # Should never reach here due to Literal type
    raise InvalidParameterError(f"Unsupported output format: {output_format}")


def download_google_trends_csv(
    geo: str = 'US',
    hours: int = 24,
    category: str = 'all',
    active_only: bool = False,
    sort_by: str = 'relevance',
    headless: bool = True,
    download_dir: Optional[str] = None,
    output_format: OutputFormat = 'csv'
) -> Union[str, 'pd.DataFrame', None]:
    """
    Download Google Trends data with configurable filters and output formats

    Args:
        geo: Country code (US, CA, UK, IN, JP, etc.)
        hours: Time period in hours (4, 24, 48, 168)
        category: Category filter (all, sports, entertainment, etc.)
        active_only: Show only active trends
        sort_by: Sort criteria (relevance, title, volume, recency)
        headless: Run browser in headless mode
        download_dir: Directory to save file
        output_format: Output format (csv, json, parquet, dataframe)

    Returns:
        Path to downloaded file (for csv/json/parquet) or DataFrame (for dataframe format),
        or None if failed

    Raises:
        InvalidParameterError: If any parameters are invalid
        BrowserError: If browser automation fails
        DownloadError: If file download fails
    """
    # Validate input parameters
    geo = validate_geo(geo)
    hours = validate_hours(hours)
    category = validate_category(category)

    # Setup download directory
    if download_dir is None:
        # Default to 'downloads' folder in current working directory
        download_dir = os.path.join(os.getcwd(), 'downloads')
    download_dir = os.path.abspath(download_dir)
    os.makedirs(download_dir, exist_ok=True)

    # Get existing files
    existing_files = set(f for f in os.listdir(download_dir) if f.endswith('.csv'))

    # Setup Chrome options
    chrome_options = Options()
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    # Suppress logging
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    print(f"[INFO] Opening Google Trends...")
    print(f"       Location: {geo}")
    print(f"       Time: Past {hours} hours")
    print(f"       Category: {category}")
    print(f"       Active only: {active_only}")
    print(f"       Sort: {sort_by}")

    # Initialize browser with error handling
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except WebDriverException as e:
        raise BrowserError(
            f"Failed to start Chrome browser: {e}\n\n"
            "Please ensure:\n"
            "1. Chrome browser is installed\n"
            "2. ChromeDriver is compatible with your Chrome version\n"
            "3. You have proper permissions\n\n"
            "ChromeDriver is auto-downloaded by Selenium, but you need Chrome browser installed."
        )

    try:
        # Build URL with parameters
        url = f"https://trends.google.com/trending?geo={geo}"

        # Add time period if not default (24 hours)
        if hours != 24:
            url += f"&hours={hours}"

        # Add category if not 'all' (uses numeric ID in URL)
        cat_code = CATEGORIES.get(category.lower(), '')
        if cat_code:
            url += f"&category={cat_code}"

        print(f"[INFO] Navigating to: {url}")
        driver.get(url)

        # Wait for page to load by checking for Export button
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Export')]"))
        )

        # Apply filters via UI if needed

        # 1. Toggle "Active trends only" if requested
        if active_only:
            try:
                print("[INFO] Enabling 'Active trends only' filter...")
                # Click the "All trends" button to open the menu
                active_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label*='select trend status']"))
                )
                active_button.click()
                time.sleep(0.5)

                # Click the toggle switch (it's a button with role="switch")
                toggle = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[role='switch'][aria-label='Show active trends only']"))
                )
                driver.execute_script("arguments[0].click();", toggle)
                time.sleep(1)

                # Press ESC to close menu
                driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                time.sleep(1)
            except (TimeoutException, NoSuchElementException) as e:
                print(f"[WARN] Could not toggle 'Active trends only' filter - using all trends")
                print(f"       Reason: UI element not found (Google may have changed their interface)")

        # 2. Apply sort if not default (relevance)
        # NOTE: Sort appears to only affect UI table display, not CSV export order
        # CSV always exports in relevance order regardless of sort selection
        if sort_by.lower() != 'relevance':
            print(f"[INFO] Note: Sort by '{sort_by}' only affects UI display (CSV exports in relevance order)")

        # Click Export button
        print("[INFO] Downloading CSV...")
        export_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Export')]"))
        )
        export_button.click()
        time.sleep(1)

        # Click Download CSV
        download_csv = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'li[data-action="csv"]'))
        )
        driver.execute_script("arguments[0].click();", download_csv)

        # Wait for download with dynamic file checking
        print("[INFO] Waiting for file download...")
        max_wait_time = 10  # Maximum 10 seconds
        check_interval = 0.5  # Check every 0.5 seconds
        elapsed_time = 0.0  # Use float to match check_interval type
        new_files: Set[str] = set()

        while elapsed_time < max_wait_time:
            time.sleep(check_interval)
            elapsed_time += check_interval

            # Check for new files
            current_files = set(f for f in os.listdir(download_dir) if f.endswith('.csv'))
            new_files = current_files - existing_files

            if new_files:
                print(f"[INFO] File detected after {elapsed_time:.1f}s")
                break

        # Final check if loop ended without finding file
        if not new_files:
            current_files = set(f for f in os.listdir(download_dir) if f.endswith('.csv'))
            new_files = current_files - existing_files

        if new_files:
            downloaded_file = list(new_files)[0]
            full_path = os.path.join(download_dir, downloaded_file)

            # Rename file with configuration info
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            new_name = f"trends_{geo}_{hours}h_{category}_{timestamp}.csv"
            new_path = os.path.join(download_dir, new_name)

            os.rename(full_path, new_path)

            print(f"[OK] Downloaded: {new_name}")
            print(f"[OK] Location: {new_path}")

            # Convert to requested format
            result = _convert_csv_to_format(new_path, output_format, download_dir)

            # Print success message based on format
            if output_format == 'dataframe':
                print(f"[OK] Converted to DataFrame with {len(result)} rows")

            return result
        else:
            raise DownloadError(
                "No new file detected after download attempt.\n\n"
                "Possible causes:\n"
                "- Download may have failed silently\n"
                "- File may have been downloaded to a different location\n"
                "- Network timeout during download\n\n"
                f"Expected download directory: {download_dir}"
            )

    except TimeoutException as e:
        raise BrowserError(
            f"Page load timeout: {e}\n\n"
            "Possible causes:\n"
            "- Slow internet connection\n"
            "- Google Trends website is down or slow\n"
            "- Network firewall blocking access\n\n"
            "Try again with a better connection or check https://trends.google.com/trending"
        )

    except NoSuchElementException as e:
        raise BrowserError(
            f"Could not find UI element: {e}\n\n"
            "Possible causes:\n"
            "- Google Trends changed their website design\n"
            "- Page did not load correctly\n\n"
            "Solutions:\n"
            "- Update trendspyg: pip install --upgrade trendspyg\n"
            "- Check GitHub issues: https://github.com/flack0x/trendspyg/issues\n"
            "- Report this issue if it persists"
        )

    except ElementClickInterceptedException as e:
        raise BrowserError(
            f"Could not click UI element: {e}\n\n"
            "An element is blocking the click. This may be temporary.\n"
            "Try running again - this often resolves automatically."
        )

    except (InvalidParameterError, BrowserError, DownloadError):
        # Re-raise our custom exceptions without wrapping
        raise

    except Exception as e:
        # Catch any other unexpected errors
        raise BrowserError(
            f"Unexpected error during download: {type(e).__name__}: {e}\n\n"
            "This is an unexpected error. Please report it at:\n"
            "https://github.com/flack0x/trendspyg/issues"
        )

    finally:
        driver.quit()


# ============================================================================
# EXPLORE ENDPOINT FUNCTIONS
# ============================================================================

def validate_date_range(date_range: str) -> str:
    """Validate date range parameter for explore endpoint.

    Args:
        date_range: Preset like 'today 5-y' or custom 'YYYY-MM-DD YYYY-MM-DD'

    Returns:
        Validated date range string

    Raises:
        InvalidParameterError: If date range format is invalid
    """
    import re

    # Check presets
    if date_range in EXPLORE_DATE_PRESETS:
        return date_range

    # Check custom range format: YYYY-MM-DD YYYY-MM-DD
    pattern = r'^\d{4}-\d{2}-\d{2} \d{4}-\d{2}-\d{2}$'
    if re.match(pattern, date_range):
        return date_range

    raise InvalidParameterError(
        f"Invalid date_range: '{date_range}'\n\n"
        f"Valid presets: {', '.join(EXPLORE_DATE_PRESETS)}\n"
        f"Or custom range: 'YYYY-MM-DD YYYY-MM-DD' (e.g., '2024-01-01 2024-12-31')"
    )


def validate_explore_category(category: Union[str, int, None]) -> Optional[int]:
    """Validate category for explore endpoint.

    Args:
        category: Category name or ID

    Returns:
        Category ID as int, or None if 'all'/0

    Raises:
        InvalidParameterError: If category is invalid
    """
    if category is None:
        return None

    # If already an int
    if isinstance(category, int):
        if category == 0:
            return None
        return category

    # String lookup
    cat_lower = category.lower().replace(' ', '_').replace('-', '_')
    if cat_lower in EXPLORE_CATEGORIES:
        cat_id = EXPLORE_CATEGORIES[cat_lower]
        return None if cat_id == 0 else cat_id

    # Try parsing as int string
    try:
        cat_id = int(category)
        return None if cat_id == 0 else cat_id
    except ValueError:
        pass

    raise InvalidParameterError(
        f"Invalid explore category: '{category}'\n\n"
        f"Available categories: {', '.join(sorted(EXPLORE_CATEGORIES.keys()))}\n"
        f"Or use numeric category ID directly."
    )


def parse_explore_csv(csv_path: str) -> Dict[str, Any]:
    """Parse multi-section explore CSV into structured data.

    The explore CSV contains multiple sections separated by blank lines:
    - Interest over time (time series)
    - Interest by region
    - Related topics (TOP and RISING)
    - Related queries (TOP and RISING)

    Args:
        csv_path: Path to downloaded CSV

    Returns:
        Dict with sections: interest_over_time, interest_by_region,
        related_topics, related_queries
    """
    import pandas as pd
    import io

    result = {
        'interest_over_time': None,
        'interest_by_region': None,
        'related_topics_top': None,
        'related_topics_rising': None,
        'related_queries_top': None,
        'related_queries_rising': None,
    }

    with open(csv_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split into sections by double newlines
    sections = content.split('\n\n')

    current_section = None
    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split('\n')
        header = lines[0].lower() if lines else ''

        # Identify section type
        if 'interest over time' in header or (len(lines) > 1 and ('week' in lines[1].lower() or 'day' in lines[1].lower() or 'month' in lines[1].lower())):
            # Skip the header line if it's a label
            data_start = 1 if 'interest' in header else 0
            data = '\n'.join(lines[data_start:])
            if data.strip():
                try:
                    df = pd.read_csv(io.StringIO(data))
                    # Convert date column
                    date_col = df.columns[0]
                    df[date_col] = pd.to_datetime(df[date_col])
                    df.set_index(date_col, inplace=True)
                    result['interest_over_time'] = df
                except Exception as e:
                    print(f"[WARN] Failed to parse interest_over_time: {e}")

        elif 'interest by' in header or 'region' in header.lower():
            data_start = 1 if 'interest' in header or 'region' in header else 0
            data = '\n'.join(lines[data_start:])
            if data.strip():
                try:
                    result['interest_by_region'] = pd.read_csv(io.StringIO(data))
                except Exception as e:
                    print(f"[WARN] Failed to parse interest_by_region: {e}")

        elif 'related topics' in header.lower():
            current_section = 'topics'

        elif 'related queries' in header.lower():
            current_section = 'queries'

        elif header.upper() == 'TOP' and current_section:
            data = '\n'.join(lines[1:])
            if data.strip():
                try:
                    key = f'related_{current_section}_top'
                    result[key] = pd.read_csv(io.StringIO(data))
                except Exception:
                    pass

        elif header.upper() == 'RISING' and current_section:
            data = '\n'.join(lines[1:])
            if data.strip():
                try:
                    key = f'related_{current_section}_rising'
                    result[key] = pd.read_csv(io.StringIO(data))
                except Exception:
                    pass

    return result


def download_google_trends_explore(
    query: Union[str, List[str], None] = None,
    date_range: str = 'today 5-y',
    geo: str = 'US',
    category: Union[str, int, None] = None,
    hl: str = 'en-US',
    headless: bool = True,
    download_dir: Optional[str] = None,
    output_format: OutputFormat = 'dataframe',
) -> Union[Dict[str, Any], 'pd.DataFrame', str, None]:
    """
    Download Google Trends explore data for historical interest analysis.

    This endpoint provides historical interest data over time, useful for
    validating evergreen content potential (stable interest over years vs
    news-driven spikes).

    Args:
        query: Search term(s) to analyze. Up to 5 terms for comparison.
               If None, browses by category (requires category param).
        date_range: Time period. Presets: 'today 5-y', 'today 12-m', 'today 3-m',
                   'today 1-m', 'now 7-d', 'now 1-d'.
                   Or custom: '2024-01-01 2024-12-31'
        geo: Country code (US, HK, GB, etc.)
        category: Category filter (name or ID). See EXPLORE_CATEGORIES.
        hl: Language code for results (e.g., 'en-US', 'zh-TW')
        headless: Run browser in headless mode
        download_dir: Directory for CSV files
        output_format: 'dataframe' returns interest_over_time DataFrame,
                      'csv' returns path, 'json' returns parsed dict

    Returns:
        - If output_format='dataframe': DataFrame of interest over time
        - If output_format='csv': Path to downloaded CSV
        - If output_format='json': Dict with all parsed sections

    Example:
        # Check 5-year interest for "data governance"
        df = download_google_trends_explore(
            query="data governance",
            date_range="today 5-y",
            geo="US"
        )
        # df shows weekly interest values (0-100) over 5 years
        # Stable line = evergreen, spike-and-fade = news-driven

        # Compare multiple terms
        df = download_google_trends_explore(
            query=["bitcoin", "ethereum", "dogecoin"],
            date_range="today 12-m",
            geo="US"
        )
    """
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
    download_dir = os.path.abspath(download_dir)
    os.makedirs(download_dir, exist_ok=True)

    # Get existing files for detection
    existing_files = set(f for f in os.listdir(download_dir) if f.endswith('.csv'))

    # Setup Chrome
    chrome_options = Options()
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    print(f"[INFO] Opening Google Trends Explore...")
    print(f"       Query: {queries if queries else '(category browse)'}")
    print(f"       Date range: {date_range}")
    print(f"       Location: {geo}")
    print(f"       Category: {category or 'all'}")
    print(f"       Language: {hl}")

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except WebDriverException as e:
        raise BrowserError(f"Failed to start Chrome browser: {e}")

    try:
        # Build URL
        # URL encode the date range (space -> %20)
        date_encoded = date_range.replace(' ', '%20')
        url = f"https://trends.google.com/trends/explore?date={date_encoded}&geo={geo}&hl={hl}"

        if queries:
            # URL encode queries and join with comma
            from urllib.parse import quote
            q_encoded = ','.join(quote(q) for q in queries)
            url += f"&q={q_encoded}"

        if cat_id:
            url += f"&cat={cat_id}"

        print(f"[INFO] Navigating to: {url}")

        # Rate limiting handling with exponential backoff + jitter
        # Using manual implementation (tenacity optional dependency)
        import random

        max_retries = 5
        base_delay = 5  # seconds

        for attempt in range(max_retries):
            driver.get(url)
            time.sleep(2)

            # Check for rate limiting
            if "429" in driver.title or "Too Many Requests" in driver.title:
                # Exponential backoff: 5, 10, 20, 40, 80 seconds
                # Plus jitter: random 0-50% of delay
                delay = base_delay * (2 ** attempt)
                jitter = delay * random.uniform(0, 0.5)
                wait_time = delay + jitter
                print(f"[WARN] Rate limited (429). Waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}...")
                print(f"       (base: {delay}s + jitter: {jitter:.1f}s)")
                time.sleep(wait_time)
                continue
            break
        else:
            raise BrowserError(
                "Google Trends rate limit (429) - too many requests after 5 retries.\n"
                "Try again later or reduce request frequency.\n"
                "Consider using proxies for high-volume access."
            )

        # Wait for page to load - look for the CSV export button on widgets
        print("[INFO] Waiting for page content...")
        try:
            # Wait for the CSV download button to appear
            # Selector: button.widget-actions-item.export[title="CSV"]
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'button.widget-actions-item.export[title="CSV"]'))
            )
            print("[OK] Found CSV export button")
        except TimeoutException:
            # Try alternate: just the export class
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.widget-actions-item.export'))
                )
                print("[OK] Found export button (alternate selector)")
            except TimeoutException:
                print("[WARN] Could not find CSV export button")
                print("[DEBUG] Page title:", driver.title)

        time.sleep(2)  # Let charts render fully

        # Click the first CSV export button (Interest over time widget)
        print("[INFO] Clicking CSV download...")
        csv_buttons = driver.find_elements(By.CSS_SELECTOR, 'button.widget-actions-item.export[title="CSV"]')

        if not csv_buttons:
            # Fallback to broader selector
            csv_buttons = driver.find_elements(By.CSS_SELECTOR, '.widget-actions-item.export')

        if csv_buttons:
            print(f"[DEBUG] Found {len(csv_buttons)} CSV export buttons")
            # Click the first one (Interest over time)
            driver.execute_script("arguments[0].click();", csv_buttons[0])
            time.sleep(1)
        else:
            print("[WARN] No CSV export buttons found - page may have no data or different structure")
            print("[DEBUG] Page title:", driver.title)

        # Wait for download
        print("[INFO] Waiting for file download...")
        max_wait = 30
        csv_path = None

        for _ in range(max_wait):
            time.sleep(1)
            current_files = set(f for f in os.listdir(download_dir) if f.endswith('.csv'))
            new_files = current_files - existing_files

            # Filter out partial downloads
            new_files = {f for f in new_files if not f.endswith('.crdownload')}

            if new_files:
                # Get most recent
                newest = max(new_files, key=lambda f: os.path.getmtime(os.path.join(download_dir, f)))
                csv_path = os.path.join(download_dir, newest)
                print(f"[OK] Downloaded: {newest}")
                break

        if not csv_path:
            raise DownloadError("Download timed out - no CSV file detected")

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

    except (InvalidParameterError, BrowserError, DownloadError):
        raise

    except Exception as e:
        raise BrowserError(f"Unexpected error: {type(e).__name__}: {e}")

    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Download Google Trends data with custom filters',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default (US, past 24 hours, all categories)
  %(prog)s

  # Canada, past 4 hours
  %(prog)s --geo CA --hours 4

  # UK, past 7 days, Sports only, sorted by volume
  %(prog)s --geo UK --hours 168 --category sports --sort volume

  # India, active trends only
  %(prog)s --geo IN --active-only

  # Japan, Entertainment category, sorted by recency
  %(prog)s --geo JP --category entertainment --sort recency

Available countries (geo codes):
  US, CA, UK, AU, IN, JP, DE, FR, BR, MX, ES, IT, RU, KR, and many more

Available categories:
  all, business, health, law, politics, technology, science
  Aliases: tech (=technology), gov/government (=law)
        """
    )

    parser.add_argument('--geo', type=str, default='US',
                       help='Country code (US, CA, UK, IN, JP, etc.). Default: US')

    parser.add_argument('--hours', type=int, choices=[4, 24, 48, 168], default=24,
                       help='Time period: 4 (4h), 24 (24h), 48 (48h), 168 (7d). Default: 24')

    parser.add_argument('--category', type=str, choices=list(CATEGORIES.keys()), default='all',
                       help='Category filter. Default: all')

    parser.add_argument('--active-only', action='store_true',
                       help='Show only active trends')

    parser.add_argument('--sort', type=str, choices=SORT_OPTIONS, default='relevance',
                       help='Sort by: relevance, title, volume, recency. Default: relevance')

    parser.add_argument('--visible', action='store_true',
                       help='Run browser in visible mode (not headless)')

    parser.add_argument('--output-dir', type=str,
                       help='Output directory for downloaded file')

    args = parser.parse_args()

    print("="*70)
    print("Google Trends Configurable Downloader")
    print("="*70)

    filepath = download_google_trends_csv(
        geo=args.geo.upper(),
        hours=args.hours,
        category=args.category,
        active_only=args.active_only,
        sort_by=args.sort,
        headless=not args.visible,
        download_dir=args.output_dir
    )

    print("="*70)

    if filepath:
        size = os.path.getsize(filepath)
        print(f"File size: {size:,} bytes")
        print("\nDone!")
        exit(0)
    else:
        print("\nFailed to download")
        exit(1)


if __name__ == "__main__":
    main()
