import asyncio
import os
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
import uuid

import aiofiles
import aiohttp
from dotenv import load_dotenv

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatBrowserUse
from browser_use.tokens.service import TokenCost

from .profile import default_profile
from .tools.playwright import playwright_tools, connect_playwright_to_cdp
from .resume import download_resume, cleanup_resume
from .prompt import default_prompt

import subprocess
import tempfile

load_dotenv()


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


def generate_webhook_signature(payload: str, secret: str) -> str:
    """
    Generate HMAC-SHA256 signature for webhook payload.

    Args:
        payload: The JSON payload as string
        secret: The webhook secret key

    Returns:
        Hex-encoded signature
    """
    if not secret:
        raise ValueError("Webhook secret is required for signing")

    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return f"sha256={signature}"


async def send_webhook(
    webhook_url: str,
    user_id: str,
    success: bool,
    metadata: Dict[str, Any] = None,
):
    """
    Send webhook notification when agent completes.

    Args:
        webhook_url: URL to send the webhook to
        user_id: User ID of the agent
        session_id: Session ID of the agent
        success: Success status of the agent
        metadata: Additional metadata to include in the webhook
    """
    if not webhook_url:
        return

    payload = {
        "success": success,
        "user_id": user_id,
        "metadata": metadata or {},
        "timestamp": int(time.time()),
    }

    # Convert payload to JSON string for signing
    import json

    payload_json = json.dumps(payload, sort_keys=True)

    # Generate signature
    webhook_secret = os.getenv("WEBHOOK_SECRET")
    headers = {"Content-Type": "application/json"}

    if webhook_secret:
        signature = generate_webhook_signature(payload_json, webhook_secret)
        headers["X-Webhook-Signature"] = signature
        headers["X-Webhook-Timestamp"] = str(payload["timestamp"])
    else:
        print("⚠️ Warning: WEBHOOK_SECRET not set, sending unsigned webhook")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                data=payload_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    print(f"✅ Webhook sent successfully to {webhook_url}")
                else:
                    response_text = await response.text()
                    print(
                        f"⚠️ Webhook failed with status {response.status}: {response_text[:200]}..."
                    )
    except aiohttp.ClientConnectorError as e:
        print(f"⚠️ Could not connect to webhook URL {webhook_url}: {e}")
    except aiohttp.ClientTimeout as e:
        print(f"⚠️ Webhook request timed out for {webhook_url}: {e}")
    except Exception as e:
        print(f"❌ Error sending webhook to {webhook_url}: {e}")


async def start_agent(
    user_id: str,
    url: str,
    profile: dict = default_profile,
    resume_url: str = "",
    instructions: str = "",
    secrets: dict = {},
    webhook_url: Optional[str] = None,
) -> str:
    """
    Main function demonstrating Browser-Use + Playwright integration with custom actions.
    Returns session_id immediately and runs agent in background with webhook notification.
    """
    if not user_id:
        raise ValueError("User ID is required")

    if not url:
        raise ValueError("URL is required")

    if not profile:
        raise ValueError("Profile is required")

    if not resume_url:
        raise ValueError("Resume URL or file path is required")

    # Start the agent process in the background
    asyncio.create_task(
        _run_agent_background(
            user_id,
            url,
            profile,
            resume_url,
            instructions,
            secrets,
            webhook_url,
        )
    )

    return str(uuid.uuid4()), "No live URL available (local browser instances)"


async def _run_agent_background(
    user_id: str,
    url: str,
    profile: dict,
    resume_url: str,
    instructions: str,
    secrets: dict,
    webhook_url: Optional[str],
):
    """
    Run the agent in the background and send webhook when complete.
    """
    file_path = None
    replay = None

    try:
        if resume_url:
            # The resume url will always be from usfs, so we can safely download it
            file_path = download_resume(resume_url)

        prompt = default_prompt(url, profile, file_path, instructions)

        chrome_process = await start_chrome_with_debug_port()
        cdp_url = "http://localhost:9222"

        # Connect Playwright to the browser
        playwright_connected = await connect_playwright_to_cdp(cdp_url)
        if not playwright_connected:
            raise Exception(
                "Failed to connect Playwright to browser. File uploads will not work."
            )

        browser_session = BrowserSession(
            cdp_url=cdp_url,
            headless=False,
            # highlight_elements=True,
            # dom_highlight_elements=True,
        )

        tc = TokenCost(include_cost=True)
        llm = ChatBrowserUse()
        tc.register_llm(llm)

        agent = Agent(
            task=prompt,
            llm=llm,
            tools=playwright_tools,
            browser_session=browser_session,
            sensitive_data=secrets if secrets else None,
            _url_shortening_limit=50,
        )

        print("🎯 Starting AI agent with custom Playwright actions...")

        result = await agent.run()

        usage_summary = await tc.get_usage_summary()

        # Prepare metadata for webhook
        metadata = {
            "total_prompt_tokens": usage_summary.total_prompt_tokens,
            "total_prompt_cached_tokens": usage_summary.total_prompt_cached_tokens,
            "total_completion_tokens": usage_summary.total_completion_tokens,
            "total_tokens": usage_summary.total_tokens,
            "total_cost": float(usage_summary.total_cost)
            if usage_summary.total_cost
            else 0.0,
            "user_id": user_id,
            "url": url,
            "duration_seconds": result.total_duration_seconds,
            "final_result": str(result.final_result),
            "success": result.is_successful(),
        }

        print(f"✅ Integration demo completed! Result: {result}")

    except Exception as e:
        print(f"❌ Error: {e}")

        # Send webhook notification for failure
        error_metadata = {
            "error": str(e),
            "user_id": user_id,
            "url": url,
        }
        await send_webhook(webhook_url, user_id, False, error_metadata)
        return

    finally:
        # Close playwright browser
        try:
            from .tools.playwright import playwright_browser, playwright_page

            if playwright_browser:
                print("🔍 Closing playwright browser")
                await playwright_browser.close()
                # Reset global variables
                import server.utils.tools.playwright as playwright_module

                playwright_module.playwright_browser = None
                playwright_module.playwright_page = None

            if playwright_browser:
                await playwright_browser.close()

            if chrome_process:
                chrome_process.terminate()
                try:
                    await asyncio.wait_for(chrome_process.wait(), 5)
                except TimeoutError:
                    chrome_process.kill()
        except Exception as cleanup_error:
            print(f"⚠️  Error closing playwright browser: {cleanup_error}")

        if file_path:
            cleanup_resume(file_path)

        print("✅ Cleanup complete")


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(start_agent())
