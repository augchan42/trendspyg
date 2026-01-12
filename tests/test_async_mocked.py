"""
Tests for async RSS functions - validation only (no network mocking)
"""
import pytest
from trendspyg.exceptions import InvalidParameterError


class TestAsyncImportError:
    """Test async import error handling"""

    def test_async_function_exists(self):
        """Test async function can be imported"""
        from trendspyg import download_google_trends_rss_async
        assert callable(download_google_trends_rss_async)

    def test_batch_async_function_exists(self):
        """Test batch async function can be imported"""
        from trendspyg import download_google_trends_rss_batch_async
        assert callable(download_google_trends_rss_batch_async)


@pytest.mark.asyncio
class TestAsyncValidation:
    """Test async parameter validation"""

    async def test_async_invalid_geo_raises_error(self):
        """Test async with invalid geo raises error"""
        from trendspyg import download_google_trends_rss_async

        with pytest.raises(InvalidParameterError) as exc_info:
            await download_google_trends_rss_async(geo='INVALID')

        assert 'Invalid geo code' in str(exc_info.value)

    async def test_async_invalid_output_format_raises_error(self):
        """Test async with invalid output format raises error"""
        from trendspyg import download_google_trends_rss_async

        with pytest.raises(InvalidParameterError) as exc_info:
            await download_google_trends_rss_async(geo='US', output_format='invalid')

        assert 'Invalid output_format' in str(exc_info.value)

    async def test_async_geo_case_insensitive(self):
        """Test async geo is case insensitive (validation passes)"""
        from trendspyg.rss_downloader import _validate_geo_rss

        # Just test validation, not full download
        assert _validate_geo_rss('us') == 'US'
        assert _validate_geo_rss('Gb') == 'GB'


class TestBatchValidation:
    """Test batch function validation"""

    def test_batch_function_signature(self):
        """Test batch function has correct signature"""
        from trendspyg import download_google_trends_rss_batch
        import inspect

        sig = inspect.signature(download_google_trends_rss_batch)
        params = list(sig.parameters.keys())

        assert 'geos' in params
        assert 'show_progress' in params

    def test_batch_async_function_signature(self):
        """Test batch async function has correct signature"""
        from trendspyg import download_google_trends_rss_batch_async
        import inspect

        sig = inspect.signature(download_google_trends_rss_batch_async)
        params = list(sig.parameters.keys())

        assert 'geos' in params
        assert 'max_concurrent' in params
