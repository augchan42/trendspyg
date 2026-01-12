"""
Tests for CSV downloader validation and helpers
"""
import pytest
from trendspyg.downloader import (
    validate_geo,
    validate_hours,
    validate_category,
)
from trendspyg.exceptions import InvalidParameterError


class TestValidateGeo:
    """Test geo validation"""

    def test_valid_country_codes(self):
        """Test valid country codes"""
        assert validate_geo('US') == 'US'
        assert validate_geo('GB') == 'GB'
        assert validate_geo('DE') == 'DE'

    def test_valid_us_states(self):
        """Test valid US state codes"""
        assert validate_geo('US-CA') == 'US-CA'
        assert validate_geo('US-NY') == 'US-NY'
        assert validate_geo('US-TX') == 'US-TX'

    def test_lowercase_to_uppercase(self):
        """Test lowercase conversion"""
        assert validate_geo('us') == 'US'
        assert validate_geo('gb') == 'GB'
        assert validate_geo('us-ca') == 'US-CA'

    def test_invalid_geo_raises_error(self):
        """Test invalid geo raises error"""
        with pytest.raises(InvalidParameterError) as exc_info:
            validate_geo('INVALID')

        assert 'Invalid geo code' in str(exc_info.value)

    def test_invalid_geo_suggests_alternatives(self):
        """Test invalid geo suggests alternatives"""
        with pytest.raises(InvalidParameterError) as exc_info:
            validate_geo('USA')

        error_msg = str(exc_info.value)
        assert 'Did you mean' in error_msg


class TestValidateHours:
    """Test hours validation"""

    def test_valid_hours(self):
        """Test valid hour values"""
        assert validate_hours(4) == 4
        assert validate_hours(24) == 24
        assert validate_hours(48) == 48
        assert validate_hours(168) == 168

    def test_invalid_hours_raises_error(self):
        """Test invalid hours raises error"""
        with pytest.raises(InvalidParameterError) as exc_info:
            validate_hours(12)

        assert 'Invalid hours value' in str(exc_info.value)
        assert '4, 24, 48, 168' in str(exc_info.value)

    def test_invalid_hours_zero(self):
        """Test zero hours raises error"""
        with pytest.raises(InvalidParameterError):
            validate_hours(0)

    def test_invalid_hours_negative(self):
        """Test negative hours raises error"""
        with pytest.raises(InvalidParameterError):
            validate_hours(-24)


class TestValidateCategory:
    """Test category validation"""

    def test_valid_categories(self):
        """Test valid categories"""
        assert validate_category('all') == 'all'
        assert validate_category('sports') == 'sports'
        assert validate_category('technology') == 'technology'
        assert validate_category('entertainment') == 'entertainment'
        assert validate_category('business') == 'business'

    def test_lowercase_category(self):
        """Test lowercase category"""
        assert validate_category('SPORTS') == 'sports'
        assert validate_category('Technology') == 'technology'
        assert validate_category('ENTERTAINMENT') == 'entertainment'

    def test_invalid_category_raises_error(self):
        """Test invalid category raises error"""
        with pytest.raises(InvalidParameterError) as exc_info:
            validate_category('invalid_category')

        assert 'Invalid category' in str(exc_info.value)

    def test_all_valid_categories(self):
        """Test all valid categories work"""
        valid_categories = [
            'all', 'sports', 'entertainment', 'business', 'politics',
            'technology', 'health', 'science', 'games', 'shopping',
            'food', 'travel', 'beauty', 'hobbies', 'climate',
            'jobs', 'law', 'pets', 'autos', 'other'
        ]
        for cat in valid_categories:
            assert validate_category(cat) == cat


class TestValidationEdgeCases:
    """Test edge cases in validation"""

    def test_empty_geo_raises_error(self):
        """Test empty geo raises error"""
        with pytest.raises(InvalidParameterError):
            validate_geo('')

    def test_whitespace_geo_raises_error(self):
        """Test whitespace geo raises error"""
        with pytest.raises(InvalidParameterError):
            validate_geo('  ')

    def test_empty_category_raises_error(self):
        """Test empty category raises error"""
        with pytest.raises(InvalidParameterError):
            validate_category('')
