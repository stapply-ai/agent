import asyncio
import os
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
# Check for required dependencies first - before other imports
try:
    import aiohttp  # type: ignore
    from playwright.async_api import Browser, Page, async_playwright  # type: ignore
except ImportError as e:
    print(f"❌ Missing dependencies for this example: {e}")
    print("This example requires: playwright aiohttp")
    print("Install with: uv add playwright aiohttp")
    print("Also run: playwright install chromium")
    sys.exit(1)

from browser_use import Agent, BrowserSession, ChatOpenAI, Tools
from browser_use.agent.views import ActionResult

from kernel import Kernel

# Global Playwright browser instance - shared between custom actions
playwright_browser: Browser | None = None
playwright_page: Page | None = None


# Custom action parameter models
class PlaywrightFileUploadAction(BaseModel):
    """Parameters for Playwright file upload action."""

    file_path: str = Field(..., description="File path to upload")
    selector: str = Field(..., description="CSS selector for the file input field")


class PlaywrightComboboxAction(BaseModel):
    """Parameters for Playwright combobox action."""

    selector: str = Field(
        ..., description="CSS selector for the combobox input element"
    )
    value: str = Field(..., description="Value to type and select from combobox")


async def start_chrome_with_debug_port(port: int = 9222):
    """
    Start Chrome with remote debugging enabled.
    Returns the Chrome process.
    """
    # Create temporary directory for Chrome user data
    user_data_dir = tempfile.mkdtemp(prefix="chrome_cdp_")

    # Chrome launch command
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
        "/usr/bin/google-chrome",  # Linux
        "/usr/bin/chromium-browser",  # Linux Chromium
        "chrome",  # Windows/PATH
        "chromium",  # Generic
    ]

    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path) or path in ["chrome", "chromium"]:
            try:
                # Test if executable works
                test_proc = await asyncio.create_subprocess_exec(
                    path,
                    "--version",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await test_proc.wait()
                chrome_exe = path
                break
            except Exception:
                continue

    if not chrome_exe:
        raise RuntimeError("❌ Chrome not found. Please install Chrome or Chromium.")

    # Chrome command arguments
    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "about:blank",  # Start with blank page
    ]

    # Start Chrome process
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Wait for Chrome to start and CDP to be ready
    cdp_ready = False
    for _ in range(20):  # 20 second timeout
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://localhost:{port}/json/version",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as response:
                    if response.status == 200:
                        cdp_ready = True
                        break
        except Exception:
            pass
        await asyncio.sleep(1)

    if not cdp_ready:
        process.terminate()
        raise RuntimeError("❌ Chrome failed to start with CDP")

    return process


async def connect_playwright_to_cdp(cdp_url: str):
    """
    Connect Playwright to the same Chrome instance Browser-Use is using.
    This enables custom actions to use Playwright functions.
    """
    global playwright_browser, playwright_page

    playwright = await async_playwright().start()
    playwright_browser = await playwright.chromium.connect_over_cdp(cdp_url)

    # Get or create a page
    if (
        playwright_browser
        and playwright_browser.contexts
        and playwright_browser.contexts[0].pages
    ):
        playwright_page = playwright_browser.contexts[0].pages[0]
    elif playwright_browser:
        context = await playwright_browser.new_context()
        playwright_page = await context.new_page()


# Create custom tools that use Playwright functions
tools = Tools()


@tools.registry.action(
    "Upload a file using Playwright's file upload capabilities. Use this when you need to upload a file to a file input field.",
    param_model=PlaywrightFileUploadAction,
)
async def playwright_file_upload(
    params: PlaywrightFileUploadAction, browser_session: BrowserSession
):
    """
    Custom action that uses Playwright to upload a file to file input elements.
    """

    print(f"Uploading file: {params.file_path}")
    print(f"Selector: {params.selector}")

    try:
        print("🔍 Starting file upload process...")

        if not playwright_page:
            print("❌ Playwright not connected. Run setup first.")
            return ActionResult(error="Playwright not connected. Run setup first.")

        print("✅ Playwright page is connected")

        # Check if the file exists
        if not os.path.exists(params.file_path):
            print(f"❌ File not found: {params.file_path}")
            return ActionResult(error=f"File not found: {params.file_path}")

        print(f"✅ File exists: {params.file_path}")
        print(f"📁 File size: {os.path.getsize(params.file_path)} bytes")

        # Wait for the page to be ready and try multiple strategies
        print("⏳ Waiting for page to be ready and dynamic content to load...")
        try:
            await playwright_page.wait_for_load_state(
                "networkidle", timeout=15000
            )  # Increased timeout
            print("✅ Page is ready (networkidle)")
        except Exception as networkidle_error:
            print(
                f"⚠️  NetworkIdle timeout, trying 'domcontentloaded' instead: {networkidle_error}"
            )
            try:
                await playwright_page.wait_for_load_state(
                    "domcontentloaded", timeout=5000
                )
                print("✅ Page is ready (domcontentloaded)")
            except Exception as dom_error:
                print(f"⚠️  DOM load also failed, continuing anyway: {dom_error}")
                print("🔄 Proceeding without waiting for page load state...")

        # Additional wait for dynamic content to load
        print("⏳ Waiting additional time for dynamic content...")
        await asyncio.sleep(3)  # Give more time for JavaScript to render components

        # Try to trigger dynamic content loading with JavaScript
        print("🔄 Triggering dynamic content with JavaScript...")
        try:
            # Trigger any click events that might load content
            await playwright_page.evaluate("""
				// Try to trigger any lazy loading
				window.dispatchEvent(new Event('scroll'));
				window.dispatchEvent(new Event('resize'));
				
				// Look for elements that might trigger file upload UI
				const uploadButtons = document.querySelectorAll('button, div, span');
				uploadButtons.forEach(btn => {
					const text = btn.textContent?.toLowerCase() || '';
					if (text.includes('upload') || text.includes('file') || text.includes('resume')) {
						console.log('Found potential upload trigger:', btn);
						// Hover to trigger any hover effects
						btn.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
					}
				});
				
				// Wait a bit for any async operations
				return new Promise(resolve => setTimeout(resolve, 1000));
			""")
            print("✅ JavaScript triggers executed")
        except Exception as js_error:
            print(f"⚠️  JavaScript execution failed: {js_error}")

        # Try to trigger any lazy-loaded content by scrolling
        print("🔄 Scrolling to trigger lazy-loaded content...")
        try:
            await playwright_page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await asyncio.sleep(1)
            await playwright_page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
        except Exception as scroll_error:
            print(f"⚠️  Scrolling failed: {scroll_error}")

        # Check for iframes that might contain the file input
        print("🔍 Checking for iframes...")
        try:
            iframes = await playwright_page.query_selector_all("iframe")
            print(f"📋 Found {len(iframes)} iframes")
            for i, iframe in enumerate(iframes):
                try:
                    src = await iframe.get_attribute("src")
                    name = await iframe.get_attribute("name")
                    iframe_id = await iframe.get_attribute("id")
                    print(
                        f"  iframe {i + 1}: src='{src}', name='{name}', id='{iframe_id}'"
                    )
                except Exception as iframe_attr_error:
                    print(
                        f"  iframe {i + 1}: Could not get attributes - {iframe_attr_error}"
                    )
        except Exception as iframe_error:
            print(f"⚠️  Error checking iframes: {iframe_error}")

        # Take a screenshot and save HTML after all loading attempts
        print("✅ Completed dynamic content loading attempts")

        print(f"🔍 Looking for file input with selector: {params.selector}")

        # First, let's debug what file-related elements are available on the page
        print("🔍 Debugging: Looking for all file-related elements on the page...")
        try:
            print("🔍 Step 1: Querying for input[type='file'] elements...")
            all_file_inputs = await playwright_page.query_selector_all(
                'input[type="file"]'
            )
            print(f"📋 Found {len(all_file_inputs)} file input elements")

            print("🔍 Step 2: Getting attributes for each file input...")
            for i, input_elem in enumerate(all_file_inputs):
                try:
                    # Get various attributes to help identify the correct input
                    input_id = await input_elem.get_attribute("id")
                    input_name = await input_elem.get_attribute("name")
                    input_class = await input_elem.get_attribute("class")
                    input_accept = await input_elem.get_attribute("accept")
                    is_hidden = await input_elem.is_hidden()

                    print(
                        f"  Input {i + 1}: id='{input_id}', name='{input_name}', class='{input_class}', accept='{input_accept}', hidden={is_hidden}"
                    )
                except Exception as attr_error:
                    print(
                        f"  ⚠️  Error getting attributes for input {i + 1}: {attr_error}"
                    )

            # Also look for buttons and divs that might trigger file uploads
            print("🔍 Step 3: Looking for upload-related buttons and elements...")
            upload_buttons = await playwright_page.query_selector_all(
                "button, div, span, a"
            )
            upload_related = []

            for button in upload_buttons:
                try:
                    text_content = await button.text_content()
                    if text_content and any(
                        keyword in text_content.lower()
                        for keyword in [
                            "upload",
                            "file",
                            "resume",
                            "attach",
                            "browse",
                            "choose",
                        ]
                    ):
                        button_tag = await button.evaluate("el => el.tagName")
                        button_id = await button.get_attribute("id")
                        button_class = await button.get_attribute("class")
                        upload_related.append(
                            {
                                "tag": button_tag,
                                "text": text_content.strip(),
                                "id": button_id,
                                "class": button_class,
                            }
                        )
                except Exception as button_error:
                    print(f"    ⚠️  Error processing upload button: {button_error}")
                    continue

            print(f"📋 Found {len(upload_related)} upload-related buttons/elements:")
            for i, elem in enumerate(upload_related[:10]):  # Limit to first 10
                print(
                    f"  Element {i + 1}: <{elem['tag']}> text='{elem['text']}', id='{elem['id']}', class='{elem['class']}'"
                )

            # Specifically look for the hidden resume input pattern
            print("🔍 Step 4: Looking for specific hidden resume input pattern...")
            try:
                hidden_resume_input = await playwright_page.query_selector(
                    'input[id*="systemfield"][id*="resume"][type="file"]'
                )
                if hidden_resume_input:
                    input_id = await hidden_resume_input.get_attribute("id")
                    is_hidden = await hidden_resume_input.is_hidden()
                    print(
                        f"  ✅ Found hidden resume input: id='{input_id}', hidden={is_hidden}"
                    )
                else:
                    print("  ❌ No hidden resume input found with expected pattern")
            except Exception as hidden_error:
                print(f"  ⚠️  Error looking for hidden resume input: {hidden_error}")

        except Exception as debug_e:
            print(f"⚠️  Debug error during file element discovery: {debug_e}")
            print(f"🔍 Error type: {type(debug_e).__name__}")
            if "Timeout" in str(debug_e):
                print(
                    "💡 This looks like a timeout - the page might still be loading or have network issues"
                )

        # Try the provided selector first - check for multiple matches
        print("🔍 Step 4: Attempting to find element with provided selector...")
        file_input = None
        selected_element = None

        try:
            print(f"  🔍 Checking for all matches of selector: {params.selector}")
            all_matches = await playwright_page.query_selector_all(params.selector)
            print(f"  📋 Found {len(all_matches)} elements matching the selector")

            if len(all_matches) > 0:
                # If multiple matches, log details about each
                for i, match in enumerate(all_matches):
                    try:
                        tag_name = await match.evaluate("el => el.tagName")
                        text_content = await match.text_content()
                        element_id = await match.get_attribute("id")
                        element_class = await match.get_attribute("class")
                        is_visible = await match.is_visible()

                        print(
                            f"    Match {i + 1}: <{tag_name}> text='{text_content}', id='{element_id}', class='{element_class}', visible={is_visible}"
                        )
                    except Exception as match_error:
                        print(
                            f"    Match {i + 1}: Error getting details - {match_error}"
                        )

                # Use the first visible match, or first match if none are visible
                for match in all_matches:
                    try:
                        is_visible = await match.is_visible()
                        if is_visible:
                            selected_element = match
                            print("  ✅ Using first visible match")
                            break
                    except Exception as visibility_error:
                        print(f"    ⚠️  Error checking visibility: {visibility_error}")
                        continue

                if not selected_element:
                    selected_element = all_matches[0]
                    print("  ⚠️  No visible matches, using first match")

                # Check if it's a file input or a button/element that might trigger file input
                tag_name = await selected_element.evaluate("el => el.tagName")
                input_type = await selected_element.get_attribute("type")

                if tag_name.lower() == "input" and input_type == "file":
                    file_input = selected_element
                    print("  ✅ Found direct file input element!")
                else:
                    print(
                        f"  🔍 Found <{tag_name}> element, checking if it triggers file input..."
                    )
                    # This might be a button that triggers a hidden file input
                    # We'll try to click it and see if a file input becomes available
                    selected_element = (
                        selected_element  # Keep reference for potential clicking
                    )
            else:
                print("  ❌ No elements found matching the selector")

        except Exception as selector_error:
            print(f"  ⚠️  Selector query failed: {selector_error}")
            print(f"  🔍 Error type: {type(selector_error).__name__}")

        # If we found a button/element but no direct file input, try clicking it first
        if not file_input and selected_element:
            print("🔍 Step 5: Trying to click element to reveal file input...")
            try:
                print("  🖱️  Clicking the selected element...")
                await selected_element.click()
                print("  ✅ Element clicked successfully")

                # Wait a moment for any file input to appear
                await asyncio.sleep(1)

                # Now try to find file inputs again
                print("  🔍 Looking for file inputs after click...")
                new_file_inputs = await playwright_page.query_selector_all(
                    'input[type="file"]'
                )
                print(f"  📋 Found {len(new_file_inputs)} file inputs after click")

                # Try to find a visible file input
                for input_elem in new_file_inputs:
                    try:
                        is_visible = await input_elem.is_visible()
                        is_hidden = await input_elem.is_hidden()
                        print(
                            f"  🔍 File input: visible={is_visible}, hidden={is_hidden}"
                        )
                        if not is_hidden:  # Use not hidden instead of is_visible for better compatibility
                            file_input = input_elem
                            print("  ✅ Found file input after click!")
                            break
                    except Exception as input_check_error:
                        print(f"    ⚠️  Error checking file input: {input_check_error}")
                        continue

            except Exception as click_error:
                print(f"  ⚠️  Failed to click element: {click_error}")

        # If still no file input, try common file input selectors
        if not file_input:
            print("🔄 Step 6: Trying fallback selectors...")
            fallback_selectors = [
                'input[type="file"]',
                "#_systemfield_resume",  # Specific to the job application form
                'input[id*="systemfield"]',
                'input[id*="resume"]',
                'input[name*="file"]',
                'input[name*="resume"]',
                'input[name*="upload"]',
                'input[accept*="pdf"]',
                'input[accept*="application"]',
                ".file-input input",
                '[data-testid*="file"] input',
                '[data-testid*="upload"] input',
            ]

            for i, selector in enumerate(fallback_selectors):
                try:
                    print(
                        f"  🔍 Trying fallback {i + 1}/{len(fallback_selectors)}: {selector}"
                    )
                    potential_inputs = await playwright_page.query_selector_all(
                        selector
                    )
                    print(f"    📋 Found {len(potential_inputs)} matches")

                    # Try each match to find a usable one
                    for j, potential_input in enumerate(potential_inputs):
                        try:
                            # For file inputs, we accept hidden ones too (they're often intentionally hidden)
                            input_type = await potential_input.get_attribute("type")
                            if input_type == "file":
                                file_input = potential_input
                                is_hidden = await potential_input.is_hidden()
                                print(
                                    f"  ✅ Found file input with fallback selector: {selector} (match {j + 1}, hidden={is_hidden})"
                                )
                                break
                            else:
                                # For non-file inputs, check visibility
                                is_hidden = await potential_input.is_hidden()
                                if not is_hidden:
                                    file_input = potential_input
                                    print(
                                        f"  ✅ Found usable element with fallback selector: {selector} (match {j + 1})"
                                    )
                                    break
                        except Exception as match_error:
                            print(f"    ⚠️  Error checking match {j + 1}: {match_error}")
                            continue

                    if file_input:
                        break

                except Exception as fallback_error:
                    print(f"    ❌ Failed: {type(fallback_error).__name__}")
                    continue

        if not file_input:
            print(
                "❌ No file input element found on the page. Make sure you are on a page with a file upload form."
            )

            # Take a screenshot and save HTML when file input is not found - only if page has meaningful content
            print(
                "📸 Taking screenshot and saving HTML after file input search failed..."
            )
            try:
                # Check if page has meaningful content before taking screenshot
                html_content = await playwright_page.content()
                body_content = await playwright_page.evaluate(
                    "() => document.body.innerText.trim()"
                )

                if (
                    body_content and len(body_content) > 50
                ):  # Only screenshot if page has substantial content
                    screenshot_path = os.path.join(os.getcwd(), "screenshots")
                    os.makedirs(screenshot_path, exist_ok=True)

                    failed_screenshot = os.path.join(
                        screenshot_path, "file_input_not_found.png"
                    )
                    await playwright_page.screenshot(
                        path=failed_screenshot, full_page=True
                    )
                    print(f"✅ Failed search screenshot saved: {failed_screenshot}")

                    # Save HTML when search fails
                    failed_html = os.path.join(
                        screenshot_path, "file_input_not_found.html"
                    )
                    with open(failed_html, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"✅ Failed search HTML saved: {failed_html}")
                else:
                    print(
                        "⚠️  Skipping screenshot - page appears to be blank or have minimal content"
                    )

            except Exception as screenshot_error:
                print(
                    f"⚠️  Failed to take failed search screenshot/HTML: {screenshot_error}"
                )

            return ActionResult(
                error="No file input element found on the page. Make sure you are on a page with a file upload form."
            )

        print("✅ File input element found")

        # Take a screenshot after successfully finding the file input
        print("📸 Taking screenshot after finding file input...")
        try:
            screenshot_path = os.path.join(os.getcwd(), "screenshots")
            found_screenshot = os.path.join(screenshot_path, "file_input_found.png")
            await playwright_page.screenshot(path=found_screenshot, full_page=True)
            print(f"✅ File input found screenshot saved: {found_screenshot}")
        except Exception as screenshot_error:
            print(f"⚠️  Failed to take file input found screenshot: {screenshot_error}")

        # Set the file on the input element
        print("🔍 Step 5: Uploading file to input element...")
        try:
            print(f"  📤 Setting file: {params.file_path}")
            await file_input.set_input_files(params.file_path)
            print("  ✅ File set on input element successfully")
        except Exception as upload_error:
            print(f"  ❌ File upload failed: {upload_error}")
            print(f"  🔍 Error type: {type(upload_error).__name__}")
            raise upload_error

        # Wait a moment for the file to be processed
        print("🔍 Step 6: Waiting for file processing...")
        print("⏳ Waiting 1 second for file to be processed...")
        await asyncio.sleep(1)

        # Verify the file was set by checking the input value
        print("🔍 Verifying file upload...")
        try:
            files = await file_input.evaluate(
                "el => el.files ? Array.from(el.files).map(f => f.name) : []"
            )
            print(f"📋 Files detected in input: {files}")
            if files:
                file_names = ", ".join(files)
                print(f"✅ File upload successful! Files: {file_names}")
                return ActionResult(
                    extracted_content=f"File(s) uploaded successfully using Playwright: {file_names}"
                )
            else:
                print("❌ No files detected in input after upload attempt")
                return ActionResult(
                    error="File upload may have failed - no files detected in input after upload attempt"
                )
        except Exception as e:
            print(f"⚠️  Verification failed with error: {str(e)}")
            # If verification fails, still report success as the upload command was executed
            return ActionResult(
                extracted_content=f"File upload command executed for: {params.file_path}. Verification failed but upload likely succeeded."
            )

    except Exception as e:
        error_msg = f"❌ Playwright file upload failed: {str(e)}"
        print(error_msg)
        print(f"🔍 Error details: {type(e).__name__}: {str(e)}")
        return ActionResult(error=error_msg)


@tools.registry.action(
    "Select an option from a combobox using Playwright's interaction capabilities. Use this when you need to type and select an option from an autocomplete/combobox input field.",
    param_model=PlaywrightComboboxAction,
)
async def playwright_combobox_select(
    params: PlaywrightComboboxAction, browser_session: BrowserSession
):
    """
    Custom action that uses Playwright to interact with combobox/autocomplete elements.
    """
    try:
        print(f"Selecting combobox option: {params.value}")
        print(f"Selector: {params.selector}")

        if not playwright_page:
            print("❌ Playwright not connected. Run setup first.")
            return ActionResult(error="Playwright not connected. Run setup first.")

        print("✅ Playwright page is connected")

        # Wait for the page to be ready
        print("⏳ Waiting for page to be ready...")
        try:
            await playwright_page.wait_for_load_state("networkidle", timeout=10000)
            print("✅ Page is ready (networkidle)")
        except Exception as networkidle_error:
            print(f"⚠️  NetworkIdle timeout: {networkidle_error}")
            try:
                await playwright_page.wait_for_load_state(
                    "domcontentloaded", timeout=5000
                )
                print("✅ Page is ready (domcontentloaded)")
            except Exception as dom_error:
                print(f"⚠️  DOM load also failed: {dom_error}")

        # Find the combobox input element
        print(f"🔍 Looking for combobox input element with selector: {params.selector}")
        combobox_input = None

        try:
            # Try to find the combobox input element
            combobox_input = await playwright_page.wait_for_selector(
                params.selector, timeout=5000
            )
            if not combobox_input:
                print(
                    f"❌ Combobox input element not found with selector: {params.selector}"
                )
                _ = input("Press Enter to continue...")
                return ActionResult(
                    error=f"Combobox input element not found with selector: {params.selector}"
                )
        except Exception as selector_error:
            print(f"❌ Failed to find combobox input element: {selector_error}")
            _ = input("Press Enter to continue...")
            return ActionResult(
                error=f"Combobox input element not found with selector: {params.selector}"
            )

        print("✅ Combobox input element found")

        # Interact with the combobox
        print(f"🔍 Interacting with combobox for value: {params.value}")
        _ = input("Press Enter to continue...")
        try:
            # First, click on the input to focus it
            print("🖱️  Clicking on combobox input to focus...")
            await combobox_input.click()
            await asyncio.sleep(0.5)

            # Clear any existing text
            print("🗑️  Clearing existing text...")
            await combobox_input.fill("")
            await asyncio.sleep(0.3)

            # Type the value to trigger autocomplete
            print(f"⌨️  Typing '{params.value}' to trigger autocomplete...")
            await combobox_input.type(
                params.value, delay=100
            )  # Add delay between keystrokes

            _ = input("Press Enter to continue...")

            # Wait for autocomplete suggestions to appear with multiple checks
            print("⏳ Waiting for dropdown options to appear...")
            dropdown_appeared = False
            for wait_attempt in range(3):  # Try up to 3 times
                await asyncio.sleep(0.5 + wait_attempt * 0.5)  # Progressive waiting
                try:
                    # Check if any dropdown options are visible
                    quick_check = await playwright_page.query_selector(
                        '[role="listbox"] [role="option"]'
                    )
                    if quick_check:
                        print(f"✅ Dropdown appeared after {wait_attempt + 1} attempts")
                        dropdown_appeared = True
                        break
                except Exception:
                    pass

            if not dropdown_appeared:
                print("⚠️  Dropdown may not have appeared, continuing anyway...")
                await asyncio.sleep(0.5)  # Final wait

            # Look for dropdown/listbox options that appear
            print("🔍 Looking for autocomplete dropdown options...")

            # First, check if floating UI portal exists
            try:
                floating_portal = await playwright_page.query_selector(
                    "[data-floating-ui-portal]"
                )
                if floating_portal:
                    print("✅ Detected floating UI portal")
                else:
                    print("⚠️  No floating UI portal detected")
            except Exception as portal_check_error:
                print(f"⚠️  Error checking for floating UI portal: {portal_check_error}")

            # Try multiple selectors for dropdown options (prioritizing floating UI structure)
            dropdown_selectors = [
                '[data-floating-ui-portal] [role="listbox"] [role="option"]',  # Floating UI structure
                '[role="listbox"] [role="option"]',  # Generic listbox options
                '[id^="floating-ui-"] [role="option"]',  # Floating UI options by ID pattern
                '[class*="_result_"] [role="option"]',  # Result container options
                '[class*="_floatingContainer_"] [role="option"]',  # Floating container options
                '[role="listbox"] div[role="option"]',  # Div-based options in listbox
                '[aria-orientation="vertical"] [role="option"]',  # Vertical orientation listbox
                '[role="listbox"] li',
                '[aria-expanded="true"] + * [role="option"]',
                '[aria-expanded="true"] + * li',
                '.dropdown [role="option"]',
                ".dropdown li",
                '[data-testid*="option"]',
                '[class*="option"]',
                "ul li",
                ".menu-item",
                '[class*="dropdown"] [class*="item"]',
            ]

            option_found = False
            for selector in dropdown_selectors:
                try:
                    print(f"  🔍 Trying dropdown selector: {selector}")
                    await playwright_page.wait_for_selector(selector, timeout=2000)
                    options = await playwright_page.query_selector_all(selector)
                    print(
                        f"  📋 Found {len(options)} options with selector: {selector}"
                    )

                    # Look for matching option
                    for i, option in enumerate(options):
                        try:
                            option_text = await option.text_content()
                            option_value = await option.get_attribute("value")
                            option_id = await option.get_attribute("id")
                            is_selected = await option.get_attribute("aria-selected")
                            print(
                                f"    Option {i + 1}: text='{option_text}', value='{option_value}', id='{option_id}', selected='{is_selected}'"
                            )

                            # Enhanced matching logic
                            text_match = option_text and (
                                params.value.lower() in option_text.lower()
                                or option_text.lower().startswith(params.value.lower())
                                or option_text.lower() == params.value.lower()
                            )
                            value_match = (
                                option_value
                                and params.value.lower() == option_value.lower()
                            )

                            if text_match or value_match:
                                print(
                                    f"  ✅ Found matching option: '{option_text}' (text_match: {text_match}, value_match: {value_match})"
                                )

                                # Scroll option into view if needed
                                try:
                                    await option.scroll_into_view_if_needed()
                                except Exception:
                                    pass  # Ignore scroll errors

                                # Click the option
                                await option.click()
                                option_found = True
                                break
                        except Exception as option_error:
                            print(
                                f"    ⚠️  Error processing option {i + 1}: {option_error}"
                            )
                            continue

                    if option_found:
                        break

                except Exception as dropdown_error:
                    print(f"  ⚠️  Dropdown selector failed: {dropdown_error}")
                    continue

            if not option_found:
                print(
                    "⚠️  No matching dropdown option found, trying keyboard navigation..."
                )
                # Try using keyboard navigation (Arrow Down + Enter)
                try:
                    await playwright_page.keyboard.press("ArrowDown")
                    await asyncio.sleep(0.3)
                    await playwright_page.keyboard.press("Enter")
                    print("✅ Used keyboard navigation to select option")
                    option_found = True
                except Exception as keyboard_error:
                    print(f"❌ Keyboard navigation failed: {keyboard_error}")

            # Wait a moment for any change events to process
            await asyncio.sleep(0.5)

            # Verify the selection
            try:
                final_value = await combobox_input.input_value()
                print(f"📋 Final combobox value: {final_value}")

                if final_value and (
                    params.value.lower() in final_value.lower()
                    or final_value.lower() in params.value.lower()
                ):
                    return ActionResult(
                        extracted_content=f"Combobox option selected successfully: {final_value}"
                    )
                elif option_found:
                    return ActionResult(
                        extracted_content=f"Combobox option selection completed for: {params.value}"
                    )
                else:
                    return ActionResult(
                        error=f"No matching option found for: {params.value}"
                    )

            except Exception as verification_error:
                print(f"⚠️  Verification failed: {verification_error}")
                if option_found:
                    return ActionResult(
                        extracted_content=f"Combobox selection command executed for: {params.value}"
                    )
                else:
                    return ActionResult(
                        error=f"Failed to select combobox option: {params.value}"
                    )

        except Exception as interaction_error:
            print(f"❌ Combobox interaction failed: {interaction_error}")
            return ActionResult(
                error=f"Failed to interact with combobox: {params.value}"
            )

    except Exception as e:
        error_msg = f"❌ Playwright combobox selection failed: {str(e)}"
        print(error_msg)
        print(f"🔍 Error details: {type(e).__name__}: {str(e)}")
        return ActionResult(error=error_msg)


async def main():
    """
    Main function demonstrating Browser-Use + Playwright integration with custom actions.
    """
    print("🚀 Advanced Playwright + Browser-Use Integration with Custom Actions")

    chrome_process = None
    try:
        # Initialize Kernel client
        client = Kernel(api_key=os.environ["KERNEL_API_KEY"])

        # Create a Kernel browser session
        kernel_browser = client.browsers.create()
        print(f"Kernel browser URL: {kernel_browser.browser_live_view_url}")
        cdp_url = kernel_browser.cdp_ws_url

        # Step 1: Start Chrome with CDP debugging
        # chrome_process = await start_chrome_with_debug_port()
        # cdp_url = "http://localhost:9222"

        # Step 2: Connect Playwright to the same Chrome instance
        await connect_playwright_to_cdp(cdp_url)

        # Step 3: Create Browser-Use session connected to same Chrome
        browser_session = BrowserSession(
            cdp_url=cdp_url,
            headless=False,
            window_size={"width": 1024, "height": 786},
            viewport={"width": 1024, "height": 786},
            device_scale_factor=1.0,
        )

        #  go_to_url = "http://localhost:5173/eval/file-upload"
        go_to_url = "https://b41414cb423f.ngrok-free.app/eval/file-upload"

        # Step 4: Create AI agent with our custom Playwright-powered tools
        agent = Agent(
            task=f"""
			Please help me apply to a job:
			
			1. First, navigate to {go_to_url}, if you see a disclaimer, click on the "Visit site" button, the website is safe.
			2. Use the 'playwright_file_upload' action to upload the file at: {go_to_url}
			   - the file is ./resume.pdf
			
            Tell me what happened.
			""",
            llm=ChatOpenAI(model="gpt-4.1-mini"),
            tools=tools,  # Our custom tools with Playwright actions
            browser_session=browser_session,
        )

        print("🎯 Starting AI agent with custom Playwright actions...")

        # Step 5: Run the agent - it will use both Browser-Use actions and our custom Playwright actions
        result = await agent.run()

        # Keep browser open briefly to see results
        print(f"✅ Integration demo completed! Result: {result}")

        client.browsers.delete_by_id(kernel_browser.session_id)
        await asyncio.sleep(2)  # Brief pause to see results

    except Exception as e:
        print(f"❌ Error: {e}")
        raise

    finally:
        # Clean up resources
        if playwright_browser:
            await playwright_browser.close()

        if chrome_process:
            chrome_process.terminate()
            try:
                await asyncio.wait_for(chrome_process.wait(), 5)
            except TimeoutError:
                chrome_process.kill()

        print("✅ Cleanup complete")


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(main())
