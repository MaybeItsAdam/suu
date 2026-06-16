"""
Form Executor - Async form automation using Playwright

This module provides reusable interaction methods for common web form patterns.
Uses Playwright's async API for compatibility with asyncio-based frameworks (FastMCP).
"""

from playwright.async_api import async_playwright, Page, BrowserContext, Locator
from typing import Dict, Any, Optional, List
import asyncio
import sys
import os
from suu.forms.schema import FormDefinition, FormField
import functools

# Redirect all print statements to stderr for MCP compatibility
print = functools.partial(print, file=sys.stderr)


class FormExecutor:
    """Executes form automations based on JSON definitions (async version)."""
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None

    # -------------------------------------------------------------------------
    # Lifecycle Methods
    # -------------------------------------------------------------------------
    
    async def start(self):
        """Starts the Playwright browser session."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

    async def stop(self):
        """Stops the Playwright browser session."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def load_auth(self, auth_file: str):
        """Loads authentication state from a file."""
        if os.path.exists(auth_file):
            print(f"Loading auth from {auth_file}")
            if self.context:
                await self.context.close()
            self.context = await self.browser.new_context(storage_state=auth_file)
            self.page = await self.context.new_page()
        else:
            print(f"Auth file {auth_file} not found. Starting fresh.")

    async def save_auth(self, auth_file: str):
        """Saves authentication state to a file."""
        await self.context.storage_state(path=auth_file)
        print(f"Saved auth to {auth_file}")

    # -------------------------------------------------------------------------
    # Reusable Interaction Methods
    # -------------------------------------------------------------------------
    
    async def wait_for_element(self, selector: str, timeout: int = 5000) -> Locator:
        """Waits for an element to be attached and returns its locator."""
        locator = self.page.locator(selector)
        try:
            await locator.first.wait_for(state="attached", timeout=timeout)
        except Exception as e:
            print(f"Timeout waiting for {selector}")
        return locator
    
    async def fill_text(self, selector: str, value: str):
        """Fills a text input using Playwright's fill() - fast but may not trigger JS."""
        locator = await self.wait_for_element(selector)
        await locator.first.fill(str(value))
    
    async def type_text(self, selector: str, value: str, delay: int = 100):
        """Types text character-by-character - slower but triggers JS events."""
        locator = await self.wait_for_element(selector)
        await locator.first.press_sequentially(str(value), delay=delay)
    
    async def type_and_enter(self, selector: str, value: str, delay: int = 100, wait_before_enter: float = 0.5):
        """Types text then presses Enter - useful for autocomplete fields."""
        locator = await self.wait_for_element(selector)
        await locator.first.press_sequentially(str(value), delay=delay)
        await asyncio.sleep(wait_before_enter)
        await locator.first.press("Enter")
    
    async def click(self, selector: str):
        """Clicks an element."""
        locator = await self.wait_for_element(selector)
        await locator.first.click()
    
    async def press_key(self, selector: str, key: str):
        """Presses a specific key on an element."""
        locator = await self.wait_for_element(selector)
        await locator.first.press(key)
    
    async def select_option(self, selector: str, value: str) -> bool:
        """
        Selects an option from a native <select> dropdown.
        Tries by value first, then by label.
        """
        locator = await self.wait_for_element(selector)
        
        # Wait for element to be enabled (handling AJAX states)
        try:
             await locator.first.expect.to_be_enabled(timeout=5000)
        except:
             print(f"Warning: Element {selector} did not become enabled, trying anyway...")

        try:
            await locator.first.select_option(value=str(value), timeout=2000, force=True)
            await self.wait_for_ajax()
            return True
        except Exception:
            try:
                await locator.first.select_option(label=str(value), timeout=2000, force=True)
                await self.wait_for_ajax()
                return True
            except Exception as e:
                try:
                    # 3. Fuzzy match: fetch all options and compare
                    options = await locator.first.evaluate(
                        "el => Array.from(el.options).map(o => ({val: o.value, text: o.text}))"
                    )
                    
                    search_norm = str(value).strip().lower()
                    best_match = None
                    
                    for opt in options:
                        text_norm = opt['text'].strip().lower()
                        # specific fix for the user's case or general fuzzy inclusions
                        if search_norm in text_norm or text_norm in search_norm:
                            print(f"Fuzzy match found: '{value}' -> '{opt['text']}'")
                            best_match = opt['val']
                            break
                    
                    if best_match:
                        await locator.first.select_option(value=best_match, timeout=2000, force=True)
                        await self.wait_for_ajax()
                        return True
                        
                    print(f"Failed to select '{value}'. Available options: {options}")
                except:
                    pass
                raise e
    
    async def select_chosen_dropdown(self, container_selector: str, search_value: str, 
                                      input_selector: str = None, type_delay: int = 100):
        """
        Handles 'Chosen' or similar custom dropdowns that require:
        1. Click to open
        2. Type to filter
        3. Press Enter to select
        """
        await self.click(container_selector)
        await asyncio.sleep(0.3)
        
        await asyncio.sleep(0.3)
        
        input_sel = input_selector or f"{container_selector} input"
        await self.type_and_enter(input_sel, search_value, delay=type_delay)
    
    async def upload_file(self, selector: str, file_path: str, 
                          validation_selector: str = None, max_retries: int = 3) -> bool:
        """
        Uploads a file with optional validation and retry logic.
        """
        locator = await self.wait_for_element(selector)
        
        for attempt in range(max_retries):
            print(f"Uploading file (attempt {attempt + 1}/{max_retries}): {file_path}")
            
            # 1. Force unhide if needed (common for styled file inputs)
            try:
                # Unconditionally unhide to be safe
                print("Forcing file input visibility...")
                await locator.first.evaluate("el => { el.style.display = 'block'; el.style.visibility = 'visible'; el.style.opacity = '1'; }")
            except Exception as e:
                print(f"Warning forcing visibility: {e}")

            # 2. Set files
            await locator.first.set_input_files(str(file_path))
            
            # Explicitly dispatch change event to trigger Drupal AJAX upload
            try:
                await locator.first.evaluate("el => el.dispatchEvent(new Event('change', {bubbles: true}))")
            except Exception as e:
                print(f"Warning dispatching change event: {e}")
            
            if validation_selector:
                try:
                    await self.page.wait_for_selector(validation_selector, timeout=15000)
                    print("File upload validated successfully.")
                    return True
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        print(f"Upload validation failed, retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"File upload failed after {max_retries} attempts: {e}")
                        raise e
            else:
                await asyncio.sleep(2)
                return True
        
        return False
    
    async def set_checkbox(self, selector: str, checked: bool):
        """Sets a checkbox to checked or unchecked state."""
        locator = await self.wait_for_element(selector)
        if checked:
            await locator.first.check()
        else:
            await locator.first.uncheck()
    
    async def wait_for_ajax(self, timeout: int = 3000):
        """Waits for network activity to settle."""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
        except:
            pass

    # -------------------------------------------------------------------------
    # Form Execution Engine
    # -------------------------------------------------------------------------

    async def execute(self, form_def: FormDefinition, data: Dict[str, Any]):
        """
        Executes the form filling process based on definition and data.
        NOTE: This NEVER submits the form. It only fills fields.
        """
        print(f"Navigating to {form_def.url}")
        await self.page.goto(form_def.url)
        await self.page.wait_for_load_state("domcontentloaded")

        for field in form_def.fields:
            # NEVER process submit fields
            if field.is_submit:
                print(f"Skipping submit field: {field.name} (Submit disabled)")
                continue

            try:
                await self._process_field(field, data)
            except Exception as e:
                print(f"Error processing field {field.name}: {e}")

    async def _process_field(self, field: FormField, data: Dict[str, Any]):
        """Routes field processing to the appropriate handler method."""
        # Handle list/group types
        if field.type in ('list', 'group'):
            await self._process_list(field, data)
            return

        value = field.value if field.value is not None else data.get(field.name)
        
        # Treat empty string as None for the purpose of defaults
        if (value is None or value == "") and field.default is not None:
            print(f"Using default value for {field.name}: {field.default}")
            value = field.default

        if value is None and field.required and field.type not in ('click', 'press_enter'):
            print(f"Skipping required field {field.name} due to missing data.")
            return

        if value is None:
            return

        print(f"Processing field: {field.name} ({field.type}) with selector: {field.selector}")
        
        if not field.selector:
            print(f"Error: Field {field.name} has no selector")
            return

        # Check visibility for non-required fields to avoid timeouts on hidden conditional fields
        if not field.required and field.selector:
            try:
                locator = self.page.locator(field.selector).first
                if not await locator.is_visible(timeout=1000):
                     print(f"Skipping hidden optional field: {field.name}")
                     return
            except Exception:
                 # If check fails, assume it might be findable logic later or let it fail naturally
                 pass

        # Route to appropriate handler
        if field.type in ('text', 'textarea'):
            await self.fill_text(field.selector, value)
        
        elif field.type == 'type_text':
            await self.type_text(field.selector, value)
        
        elif field.type == 'type_and_enter':
            await self.type_and_enter(field.selector, value)
        
        elif field.type == 'select':
            await self.select_option(field.selector, value)
            # Drupal often triggers AJAX on select changes, and select_option now handles it, 
            # but we can double check or rely on the method.
        
        elif field.type == 'checkbox':
            checked = str(value).lower() in ('true', 'yes', '1', 'on')
            await self.set_checkbox(field.selector, checked)
        
        elif field.type == 'file':
            await self.upload_file(field.selector, value, field.validation_selector)
            return  # Skip generic validation
        
        elif field.type == 'click':
            await self.click(field.selector)
        
        elif field.type == 'press_enter':
            await self.press_key(field.selector, "Enter")
            
        elif field.type == 'chosen_select':
            await self.select_chosen_dropdown(field.selector, value)

        elif field.type == 'autocomplete':
            await self.perform_autocomplete(field.selector, value)
        
        else:
            print(f"Unknown field type: {field.type}")

    async def perform_autocomplete(self, selector: str, value: str):
        """
        Handles Drupal Entity Autocomplete fields.
        1. Types the value.
        2. Waits for the .ui-autocomplete list to appear.
        3. Selects the first option.
        """
        locator = await self.wait_for_element(selector)
        await locator.first.fill(value)
        # Trigger keyup/search if needed, sometimes just fill works, but typing a space ensures it
        # await locator.first.type(" ") # Optional
        
        # Wait for the autocomplete dropdown
        # Usually appended to body or after input. Drupal uses jQuery UI.
        # Selector: .ui-autocomplete.ui-menu
        try:
             # Wait for the spinner or results
            await self.page.wait_for_selector('.ui-autocomplete .ui-menu-item', state='visible', timeout=5000)
            
            # Click the first option
            # Note: Playwright might need to locate specific item
            option = self.page.locator('.ui-autocomplete .ui-menu-item').first
            await option.click()
        except Exception as e:
            print(f"Warning: Autocomplete suggestion not found or failed to select for {selector}: {e}")
            # Fallback: Just press Enter?
            await locator.first.press("Enter")


    async def _process_list(self, field: FormField, data: Dict[str, Any]):
        """Handles repeating/list fields (e.g., multiple receipt rows)."""
        items = data.get(field.name, [])
        if not items:
            print(f"No data for list field {field.name}")
            return
            
        print(f"Processing list {field.name} with {len(items)} items")
        
        # Add extra rows if needed (first row usually exists)
        if len(items) > 1 and field.add_button_selector:
            for i in range(len(items) - 1):
                print(f"Clicking add button: {field.add_button_selector}")
                try:
                    # Provide a custom retry for the add button as it involves AJAX
                    btn = self.page.locator(field.add_button_selector).first
                    # Wait for it to become enabled (up to 5s)
                    try: 
                        await btn.expect.to_be_enabled(timeout=5000)
                    except:
                        pass

                    if await btn.is_enabled():
                        print(f"Clicking Add button for row {i+2}...")
                        # Ensure button is in view
                        await btn.scroll_into_view_if_needed()
                        await btn.click(force=True)
                        await self.wait_for_ajax()
                        
                        # Explicitly wait for the new row to appear
                        # Expecting row index i+1 (since i starts at 0 for the first ADD, which creates row 1)
                        if field.fields:
                            # Try to find a selector to wait for from the first child field
                            for child in field.fields:
                                if child.selector and ("{i}" in child.selector or "{n}" in child.selector):
                                    new_row_selector = child.selector.replace('{i}', str(i+1)).replace('{n}', str(i+2))
                                    # Clean up complex selectors to get the main element
                                    if " " in new_row_selector:
                                        new_row_selector = new_row_selector.split(" ")[0]
                                    
                                    print(f"Waiting for new row element: {new_row_selector}")
                                    try:
                                        await self.page.wait_for_selector(new_row_selector, state='attached', timeout=10000)
                                        print(f"Row {i+2} confirmed attached.")
                                    except Exception as e:
                                        print(f"Warning: Timeout waiting for new row {i+2}: {e}")
                                    break
                    else:
                        print("Add button is disabled or invalid, skipping row addition.")
                        break
                except Exception as e:
                    print(f"Warning: Failed to add row {i+2}: {e}")
                    # Try to continue filling what we have headers for
        
        # Wait for all rows to be ready
        await self._wait_for_list_rows(field, len(items))
        
        # Process each item
        for i, item_data in enumerate(items):
            print(f"Processing item {i+1}/{len(items)} in {field.name}")
            try:
                await self._process_list_item(field, item_data, i)
            except Exception as e:
                print(f"Error processing list item {i+1}: {e}")
    
    async def _wait_for_list_rows(self, field: FormField, expected_count: int):
        """Waits for the expected number of list rows to be present."""
        print("Waiting for all rows to be ready...")
        try:
            if field.fields:
                last_index = expected_count - 1
                for child in field.fields:
                    if child.selector and ("{n}" in child.selector or "{i}" in child.selector):
                        sel = child.selector.format(n=last_index+1, i=last_index)
                        row_sel = sel.split(" ")[0] if " " in sel else sel
                        await self.page.locator(row_sel).first.wait_for(state="attached", timeout=10000)
                        break
        except Exception as e:
            print(f"Warning waiting for rows: {e}")
    
    async def _process_list_item(self, field: FormField, item_data: Dict[str, Any], index: int):
        """Processes a single item in a list field."""
        if not field.fields:
            return
            
        for child_field in field.fields:
            if not child_field.selector:
                continue
                
            # Interpolate index placeholders
            if "{i}" in child_field.selector or "{n}" in child_field.selector:
                temp_field = child_field.model_copy()
                temp_field.selector = child_field.selector.format(i=index, n=index+1)
                
                # Also interpolate validation_selector
                if temp_field.validation_selector:
                    if "{i}" in temp_field.validation_selector or "{n}" in temp_field.validation_selector:
                        temp_field.validation_selector = temp_field.validation_selector.format(i=index, n=index+1)
                
                try:
                    await self._process_field(temp_field, item_data)
                except Exception as e:
                    print(f"Error filling field {child_field.name} in row {index+1}: {e}")
            else:
                try:
                    await self._process_field(child_field, item_data)
                except Exception as e:
                    print(f"Error filling field {child_field.name} in row {index+1}: {e}")
