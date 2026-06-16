import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from suu.forms.executor import FormExecutor
from suu.forms.schema import FormDefinition, FormField

@pytest.mark.asyncio
async def test_executor_start_stop():
    """Test that start/stop calls playwright methods correctly."""
    with patch('suu.forms.executor.async_playwright') as mock_playwright:
        # Setup mocks
        mock_p_ctx = AsyncMock()
        # async_playwright() returns a context manager. start() is an async method on it.
        mock_playwright.return_value.start = AsyncMock(return_value=mock_p_ctx)
        
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        mock_p_ctx.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        
        executor = FormExecutor(headless=True)
        await executor.start()
        
        # Verify startup calls
        mock_playwright.return_value.start.assert_called_once()
        mock_p_ctx.chromium.launch.assert_called_with(headless=True)
        mock_browser.new_context.assert_called_once()
        mock_context.new_page.assert_called_once()
        
        await executor.stop()
        
        # Verify shutdown calls
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_p_ctx.stop.assert_called_once()

@pytest.mark.asyncio
async def test_fill_text():
    """Test the fill_text method."""
    executor = FormExecutor()
    executor.page = AsyncMock()
    mock_locator = AsyncMock()
    executor.wait_for_element = AsyncMock(return_value=mock_locator)
    
    await executor.fill_text("#test", "hello")
    
    executor.wait_for_element.assert_called_with("#test")
    mock_locator.first.fill.assert_called_with("hello")

@pytest.mark.asyncio
async def test_process_submit_field_skipped(sample_form_def):
    """Test that submit fields are strictly skipped."""
    executor = FormExecutor()
    executor.page = AsyncMock()
    executor._process_field = AsyncMock()
    
    # Add a submit field
    submit_field = FormField(name="submit", selector="#submit", type="click", is_submit=True)
    sample_form_def.fields.append(submit_field)
    
    await executor.execute(sample_form_def, {})
    
    # Should NOT process the submit field
    # We expect 3 calls for the 3 non-submit fields in sample_form_def
    assert executor._process_field.call_count == 3 
