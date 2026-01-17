"""
trendspyg - Free, open-source Python library for Google Trends data

A modern alternative to pytrends with 188,000+ configuration options.
Download real-time Google Trends data with support for 125 countries,
51 US states, 20 categories, and multiple output formats.

Core functionality:
- **RSS Feed** (fast path): Rich media data with images & news articles (0.2s)
- **CSV Export** (full path): Comprehensive trend data with filtering (10s)
- **Stealth Mode**: Anti-detection browser for reduced CAPTCHA/rate limiting
- Multiple output formats (CSV, JSON, Parquet, DataFrame)
- Active trends filtering and sorting options

Choose your data source:
- Use RSS for: Real-time monitoring, news context, images, qualitative research
- Use CSV for: Large datasets, time filtering, statistical analysis, quantitative research
- Use Stealth for: Historical data (5yr), evergreen validation, reduced bot detection
"""

__version__ = "0.4.1"
__author__ = "flack0x"
__license__ = "MIT"

from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# Import core downloaders
from .downloader import (
    download_google_trends_csv,
    download_google_trends_explore,
    EXPLORE_CATEGORIES,
    EXPLORE_DATE_PRESETS,
    OutputFormat,
)
from .rss_downloader import (
    download_google_trends_rss,
    download_google_trends_rss_async,
    download_google_trends_rss_batch,
    download_google_trends_rss_batch_async,
)

# Import cache utilities
from .utils import (
    clear_rss_cache,
    get_rss_cache_stats,
    set_rss_cache_ttl,
)

# Import stealth downloader (optional - requires scrapling)
try:
    from .stealth_downloader import (
        download_google_trends_explore_stealth,
        SCRAPLING_AVAILABLE,
    )
except ImportError:
    # scrapling not installed - provide stub
    SCRAPLING_AVAILABLE = False
    def download_google_trends_explore_stealth(
        query: Union[str, List[str], None] = None,
        date_range: str = 'today 5-y',
        geo: str = 'US',
        category: Union[str, int, None] = None,
        hl: str = 'en-US',
        headless: bool = False,
        download_dir: Optional[str] = None,
        output_format: OutputFormat = 'dataframe',
        real_chrome: bool = False,
        cdp_url: Optional[str] = None,
        user_data_dir: Optional[str] = None,
        hide_canvas: bool = True,
        block_webrtc: bool = True,
        timeout: int = 60000,
    ) -> Union[Dict[str, Any], 'pd.DataFrame', str, None]:
        raise ImportError(
            "scrapling is required for stealth mode.\n"
            "Install with: pip install scrapling[all]\n"
            "Then run: scrapling install"
        )

# Export public API
__all__ = [
    "__version__",
    # Core downloaders
    "download_google_trends_csv",              # Full-featured CSV download (480 trends, filtering)
    "download_google_trends_explore",          # Historical interest analysis (5yr, Selenium)
    "download_google_trends_explore_stealth",  # Historical interest (5yr, Scrapling stealth)
    "download_google_trends_rss",              # Fast RSS download (rich media, news articles)
    "download_google_trends_rss_async",        # Async RSS download for parallel fetching
    "download_google_trends_rss_batch",        # Batch RSS download with progress bar
    "download_google_trends_rss_batch_async",  # Async batch RSS with progress bar (fastest)
    # Constants
    "EXPLORE_CATEGORIES",                      # Category IDs for explore endpoint
    "EXPLORE_DATE_PRESETS",                    # Valid date range presets
    "SCRAPLING_AVAILABLE",                     # Whether scrapling is installed
    # Cache control
    "clear_rss_cache",                         # Clear all cached RSS data
    "get_rss_cache_stats",                     # Get cache statistics (hits, misses, size)
    "set_rss_cache_ttl",                       # Set cache TTL (0 to disable)
]
