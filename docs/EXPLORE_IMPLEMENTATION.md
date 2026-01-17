# Implementation Plan: Google Trends Explore Endpoint

## Overview

Add support for `/trends/explore` endpoint to enable historical interest analysis for evergreen content validation.

## Current vs New Capability

| Feature | `/trending` (current) | `/trends/explore` (new) |
|---------|----------------------|-------------------------|
| URL | `trends.google.com/trending` | `trends.google.com/trends/explore` |
| Purpose | Real-time trending topics | Historical interest over time |
| Time range | 4h, 24h, 48h, 7d | 5 years, 12 months, custom ranges |
| Query | Browse by category | Search term OR category |
| Output | List of topics + volume | Time series (interest 0-100) |
| Evergreen signal | Weak | **Strong** |

## URL Structure Analysis

### Current (Trending)
```
https://trends.google.com/trending?geo=US&hours=168&category=18
```

### New (Explore)
```
# Past 5 years, Hong Kong, no query (category browsing)
https://trends.google.com/trends/explore?date=today%205-y&geo=HK&hl=en-US

# Specific year range
https://trends.google.com/trends/explore?date=2024-01-01%202024-12-31&geo=HK&hl=en-US

# With search query
https://trends.google.com/trends/explore?date=today%205-y&geo=HK&q=bitcoin&hl=en-US

# With category filter (different IDs than /trending!)
https://trends.google.com/trends/explore?date=today%205-y&geo=HK&cat=7&hl=en-US

# Compare multiple queries (up to 5)
https://trends.google.com/trends/explore?date=today%205-y&geo=HK&q=bitcoin,ethereum,dogecoin&hl=en-US
```

### Date Format Options
| Format | Meaning | Example |
|--------|---------|---------|
| `today 5-y` | Past 5 years | 2021-01-17 to 2026-01-17 |
| `today 12-m` | Past 12 months | 2025-01-17 to 2026-01-17 |
| `today 3-m` | Past 3 months | 2025-10-17 to 2026-01-17 |
| `today 1-m` | Past 1 month | 2025-12-17 to 2026-01-17 |
| `now 7-d` | Past 7 days | Real-time data |
| `now 1-d` | Past 24 hours | Real-time data |
| `YYYY-MM-DD YYYY-MM-DD` | Custom range | `2024-01-01 2024-12-31` |

### Category IDs (Explore - different from Trending!)
Note: Explore uses pytrends-style category IDs, not trending page IDs.

```python
EXPLORE_CATEGORIES = {
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
    # Useful subcategories
    'ai_ml': 1299,              # Machine Learning & AI
    'computer_security': 314,   # Cybersecurity
    'investing': 107,
    'politics': 396,
}
```

## CSV Output Structure

### Explore CSV Format
The explore page exports a multi-part CSV with sections:

```csv
Category: All categories

Interest over time
Week,bitcoin
2021-01-17,47
2021-01-24,52
2021-01-31,61
...

Interest by region
Region,bitcoin
El Salvador,100
Nigeria,54
...

Related topics
TOP
Topic,bitcoin
Bitcoin,100
Cryptocurrency,45
...

RISING
Topic,bitcoin
Bitcoin halving,Breakout
...

Related queries
TOP
Query,bitcoin
bitcoin price,100
...

RISING
Query,bitcoin
bitcoin etf,+4850%
...
```

## Proposed API

### New Function: `download_google_trends_explore()`

```python
def download_google_trends_explore(
    # Query parameters
    query: str | list[str] | None = None,  # Search term(s), up to 5

    # Time parameters
    date_range: str = 'today 5-y',  # Preset or custom range

    # Location parameters
    geo: str = 'US',

    # Category filter (optional, uses explore category IDs)
    category: str | int | None = None,

    # Language
    hl: str = 'en-US',

    # Output options
    headless: bool = True,
    download_dir: str | None = None,
    output_format: Literal['csv', 'json', 'dataframe'] = 'dataframe',

    # Data sections to extract
    sections: list[str] = ['interest_over_time', 'related_queries'],
) -> dict | pd.DataFrame | str:
    """
    Download Google Trends explore data for historical interest analysis.

    Args:
        query: Search term(s) to analyze. If None, browses by category.
        date_range: Time period. Presets: 'today 5-y', 'today 12-m', 'today 3-m',
                   'today 1-m', 'now 7-d', 'now 1-d'. Or custom: '2024-01-01 2024-12-31'
        geo: Country code (US, HK, GB, etc.)
        category: Category filter (name or ID). See EXPLORE_CATEGORIES.
        hl: Language code for results
        headless: Run browser in headless mode
        download_dir: Directory for CSV files
        output_format: Output format
        sections: Which data sections to extract from CSV

    Returns:
        Dict with sections as keys, or DataFrame for interest_over_time only

    Example:
        # Validate if "data governance" has evergreen interest
        result = download_google_trends_explore(
            query="data governance",
            date_range="today 5-y",
            geo="US",
        )
        # result['interest_over_time'] shows 5-year trend
        # Stable line = evergreen, spike-and-fade = news-driven
    """
```

### Helper Functions

```python
def validate_date_range(date_range: str) -> str:
    """Validate and normalize date range parameter."""
    presets = ['today 5-y', 'today 12-m', 'today 3-m', 'today 1-m', 'now 7-d', 'now 1-d']
    if date_range in presets:
        return date_range

    # Check custom range format: YYYY-MM-DD YYYY-MM-DD
    import re
    pattern = r'^\d{4}-\d{2}-\d{2} \d{4}-\d{2}-\d{2}$'
    if re.match(pattern, date_range):
        return date_range

    raise InvalidParameterError(f"Invalid date_range: {date_range}")


def parse_explore_csv(csv_path: str, sections: list[str]) -> dict:
    """Parse multi-section explore CSV into structured data."""
    import pandas as pd

    result = {}

    with open(csv_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by section headers
    # ... parsing logic for each section

    return result
```

## Integration with Evergreen Workflow

### New Script: `evergreen_validator.py`

```python
"""
Validate trending topics for evergreen potential using /trends/explore.

Workflow:
1. Take topics from agent-intake.json structural_candidates
2. For each topic, check 5-year interest pattern
3. Classify as: evergreen-stable, evergreen-growing, seasonal, news-spike
4. Output validated candidates with confidence scores
"""

from trendspyg import download_google_trends_explore

def validate_evergreen_potential(topic: str, geo: str = 'US') -> dict:
    """
    Check if a topic has evergreen interest pattern.

    Returns:
        {
            'topic': str,
            'classification': 'evergreen-stable' | 'evergreen-growing' | 'seasonal' | 'news-spike',
            'confidence': float,  # 0-1
            'avg_interest': float,  # Average interest over period
            'volatility': float,  # Standard deviation (high = news-driven)
            'trend_direction': float,  # Positive = growing, negative = declining
        }
    """
    # Get 5-year data
    result = download_google_trends_explore(
        query=topic,
        date_range='today 5-y',
        geo=geo,
        sections=['interest_over_time']
    )

    df = result['interest_over_time']

    # Calculate metrics
    avg_interest = df[topic].mean()
    volatility = df[topic].std()

    # Linear regression for trend direction
    from scipy import stats
    slope, _, _, _, _ = stats.linregress(range(len(df)), df[topic])

    # Classification logic
    if volatility < 15 and avg_interest > 20:
        classification = 'evergreen-stable'
        confidence = 0.9
    elif volatility < 20 and slope > 0.1:
        classification = 'evergreen-growing'
        confidence = 0.8
    elif volatility > 30:
        classification = 'news-spike'
        confidence = 0.7
    else:
        classification = 'seasonal'
        confidence = 0.6

    return {
        'topic': topic,
        'classification': classification,
        'confidence': confidence,
        'avg_interest': round(avg_interest, 2),
        'volatility': round(volatility, 2),
        'trend_direction': round(slope, 4),
    }
```

## Implementation Steps

### Phase 1: Core Function
1. [ ] Add `EXPLORE_CATEGORIES` dict with pytrends-style IDs
2. [ ] Add `validate_date_range()` function
3. [ ] Add `download_google_trends_explore()` function
4. [ ] Add `parse_explore_csv()` for multi-section parsing
5. [ ] Export new function in `__init__.py`

### Phase 2: CSV Parsing
1. [ ] Handle multi-section CSV format
2. [ ] Parse interest_over_time to DataFrame
3. [ ] Parse related_queries (TOP and RISING)
4. [ ] Parse related_topics (TOP and RISING)
5. [ ] Handle regional interest data

### Phase 3: Integration
1. [ ] Create `evergreen_validator.py` script
2. [ ] Integrate with `agent-intake.json` pipeline
3. [ ] Add validation step to `trends_discovery.py`
4. [ ] Update ADR-084 with explore endpoint docs

## Testing

```python
# Test 1: Basic 5-year query
result = download_google_trends_explore(
    query="artificial intelligence",
    date_range="today 5-y",
    geo="US"
)
assert 'interest_over_time' in result
assert len(result['interest_over_time']) > 200  # ~260 weekly data points

# Test 2: Multiple queries comparison
result = download_google_trends_explore(
    query=["bitcoin", "ethereum", "dogecoin"],
    date_range="today 12-m",
    geo="US"
)
assert all(col in result['interest_over_time'].columns for col in ["bitcoin", "ethereum", "dogecoin"])

# Test 3: Category browsing (no query)
result = download_google_trends_explore(
    category="ai_ml",
    date_range="today 5-y",
    geo="HK"
)
# Returns trending topics in AI/ML category over 5 years
```

## References

- Google Trends Explore: https://trends.google.com/trends/explore
- pytrends categories: https://github.com/pat310/google-trends-api/wiki/Google-Trends-Categories
- ADR-081: Evergreen SEO Content Strategy
- ADR-083: Google Trends Methodology for Evergreen Content
