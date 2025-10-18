import asyncio
import os
import hmac
import hashlib
import shutil
import socket
import time
import urllib.parse
from typing import Dict, Any, Optional
import uuid

import aiohttp
from dotenv import load_dotenv

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatBrowserUse

from .profile import default_profile
from .tools.playwright import playwright_tools, connect_playwright_to_cdp
from .resume import download_resume, cleanup_resume
from .prompt import default_prompt

import tempfile
import subprocess

load_dotenv()


def _env_flag(value: Optional[str]) -> bool:
    """
    Normalise environment boolean strings.
    """
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> Optional[int]:
    """
    Read an integer from the environment if available.
    """
    value = os.getenv(name)
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        print(f"⚠️  Invalid value for {name}={value!r}, ignoring.")
        return None


def _env_float(name: str) -> Optional[float]:
    """
    Read a float from the environment if available.
    """
    value = os.getenv(name)
    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        print(f"⚠️  Invalid value for {name}={value!r}, ignoring.")
        return None


CHROME_DEBUG_ADDRESS = os.getenv("CHROME_DEBUG_ADDRESS", "127.0.0.1")
LIVE_VIEW_HOST = os.getenv("LIVE_VIEW_HOST") or CHROME_DEBUG_ADDRESS
if LIVE_VIEW_HOST in ("0.0.0.0", "", None):
    LIVE_VIEW_HOST = "127.0.0.1"

CHROME_HEADLESS = _env_flag(os.getenv("CHROME_HEADLESS")) or False


def _find_free_port(bind_host: str = "127.0.0.1") -> int:
    """
    Ask the OS for a free TCP port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        return sock.getsockname()[1]


def _debug_connect_host(debug_address: str) -> str:
    """
    Hostname used by local processes to talk to Chrome.
    """
    if debug_address in ("0.0.0.0", "", None):
        return "127.0.0.1"
    if debug_address == "localhost":
        return "127.0.0.1"
    return debug_address


async def start_chrome_with_debug_port(
    port: Optional[int] = None, debug_address: str = CHROME_DEBUG_ADDRESS
):
    """
    Start Chrome with remote debugging enabled.
    Returns the Chrome process, port, and user data directory.
    """
    if port is None:
        bind_host = "127.0.0.1" if debug_address == "0.0.0.0" else debug_address
        port = _find_free_port(bind_host)

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
        f"--remote-debugging-address={debug_address}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "about:blank",  # Start with blank page
    ]

    if CHROME_HEADLESS:
        window_size_flag = None
        # if CHROME_HEADLESS_WIDTH and CHROME_HEADLESS_HEIGHT:
        #     window_size_flag = (
        #         f"--window-size={CHROME_HEADLESS_WIDTH},{CHROME_HEADLESS_HEIGHT}"
        #     )
        # elif CHROME_HEADLESS_WIDTH or CHROME_HEADLESS_HEIGHT:
        #     print(
        #         "⚠️  Both CHROME_HEADLESS_WIDTH and CHROME_HEADLESS_HEIGHT must be set "
        #         "to override the window size."
        #     )

        cmd.extend(
            [
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--mute-audio",
            ]
        )
        # if window_size_flag:
        #     cmd.append(window_size_flag)

    # Start Chrome process
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Wait for Chrome to start and CDP to be ready
    cdp_ready = False
    connect_host = _debug_connect_host(debug_address)

    for _ in range(20):  # 20 second timeout
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{connect_host}:{port}/json/version",
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
        try:
            await process.wait()
        except Exception:
            pass
        raise RuntimeError("❌ Chrome failed to start with CDP")

    mode = "headless" if CHROME_HEADLESS else "headed"
    print(f"✅ Chrome started ({mode}) with CDP on {debug_address}:{port}")

    return process, port, user_data_dir, connect_host


def _rewrite_ws_value(value: str, host: str, port: int) -> str:
    """
    Adjust websocket debugger target to use the public host.
    """
    if host in {"127.0.0.1", "localhost"}:
        return value

    if value.startswith(("ws://", "wss://")):
        parsed = urllib.parse.urlparse(value)
        current_port = parsed.port or port
        new_netloc = f"{host}:{current_port}"
        return urllib.parse.urlunparse(parsed._replace(netloc=new_netloc))

    if "://" not in value:
        if "/" in value:
            _, remainder = value.split("/", 1)
            return f"{host}:{port}/{remainder}"
        return f"{host}:{port}"

    return value


def _rewrite_devtools_url(
    url: str, public_host: str, port: int, connect_host: str
) -> str:
    """
    Rewrites a DevTools URL to use the configured public host when needed.
    """
    if not url:
        return url

    if url.startswith("/"):
        absolute_url = f"http://{connect_host}:{port}{url}"
    elif "://" not in url:
        absolute_url = f"http://{connect_host}:{port}/{url.lstrip('/')}"
    else:
        absolute_url = url

    if public_host in {"127.0.0.1", "localhost"}:
        return absolute_url

    parsed = urllib.parse.urlparse(absolute_url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    ws_values = query.get("ws")

    if ws_values:
        query["ws"] = [_rewrite_ws_value(ws_values[0], public_host, port)]

    new_query = urllib.parse.urlencode(query, doseq=True)

    netloc = parsed.netloc
    if netloc in {connect_host, f"{connect_host}:{port}"}:
        netloc = f"{public_host}:{port}"

    return urllib.parse.urlunparse(parsed._replace(netloc=netloc, query=new_query))


async def resolve_live_view_url(
    port: int, connect_host: str, public_host: str = LIVE_VIEW_HOST
) -> Optional[str]:
    """
    Try to build a DevTools frontend URL that can render the live browser view.
    Prefers the hosted compat URL when available so it works in any browser.
    """
    base_url = f"http://{connect_host}:{port}"
    endpoints = (f"{base_url}/json/list", f"{base_url}/json")
    last_error: Optional[Exception] = None

    timeout = aiohttp.ClientTimeout(total=2)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(1, 8):
            for endpoint in endpoints:
                try:
                    async with session.get(endpoint) as response:
                        if response.status != 200:
                            continue
                        targets = await response.json()

                    for target in targets:
                        if target.get("type") != "page":
                            continue

                        compat_url = target.get("devtoolsFrontendUrlCompat")
                        if compat_url:
                            return _rewrite_devtools_url(
                                compat_url, public_host, port, connect_host
                            )

                        frontend_url = target.get("devtoolsFrontendUrl")
                        if frontend_url:
                            return _rewrite_devtools_url(
                                frontend_url, public_host, port, connect_host
                            )
                except Exception as exc:
                    last_error = exc
            await asyncio.sleep(0.5 * attempt)

    if last_error:
        print(f"⚠️  Unable to resolve DevTools live view URL: {last_error}")

    return None


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
) -> tuple[str, str]:
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

    (
        chrome_process,
        chrome_port,
        user_data_dir,
        connect_host,
    ) = await start_chrome_with_debug_port()
    cdp_url = f"http://{connect_host}:{chrome_port}"
    public_cdp_url = f"http://{LIVE_VIEW_HOST}:{chrome_port}"

    live_view_url = await resolve_live_view_url(
        chrome_port, connect_host, LIVE_VIEW_HOST
    )
    if live_view_url:
        print(f"🔗 Live browser view available at: {live_view_url}")
    else:
        live_view_url = f"{public_cdp_url}/json"
        print(
            "⚠️  Could not determine DevTools frontend URL. "
            f"Access the raw CDP targets at {live_view_url}"
        )

    session_id = str(uuid.uuid4())

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
            cdp_url,
            chrome_process,
            user_data_dir,
        )
    )

    return session_id, live_view_url


async def _run_agent_background(
    user_id: str,
    url: str,
    profile: dict,
    resume_url: str,
    instructions: str,
    secrets: dict,
    webhook_url: Optional[str],
    cdp_url: str,
    chrome_process: asyncio.subprocess.Process,
    user_data_dir: str,
):
    """
    Run the agent in the background and send webhook when complete.
    """
    file_path = None

    try:
        if resume_url:
            # The resume url will always be from usfs, so we can safely download it
            file_path = download_resume(resume_url)

        prompt = default_prompt(url, profile, file_path, instructions)

        # Connect Playwright to the browser
        playwright_connected = await connect_playwright_to_cdp(cdp_url)
        if not playwright_connected:
            raise Exception(
                "Failed to connect Playwright to browser. File uploads will not work."
            )

        browser_session = BrowserSession(
            cdp_url=cdp_url,
            headless=CHROME_HEADLESS,
            # highlight_elements=True,
            # dom_highlight_elements=True,
        )

        llm = ChatBrowserUse()

        agent = Agent(
            task=prompt,
            llm=llm,
            tools=playwright_tools,
            browser_session=browser_session,
            sensitive_data=secrets if secrets else None,
            _url_shortening_limit=50,
            calculate_cost=True,
        )

        print("🎯 Starting AI agent with custom Playwright actions...")

        result = await agent.run()

        print("🔍 AGENT IS DONE! Saving result to file...")

        # Convert cost data to serializable format
        cost_data = {}
        if result.usage.by_model:
            for model, usage_stats in result.usage.by_model.items():
                cost_data[model] = {
                    "prompt_tokens": usage_stats.prompt_tokens,
                    "completion_tokens": usage_stats.completion_tokens,
                    "total_tokens": usage_stats.total_tokens,
                    "cost": usage_stats.cost,
                    "cached_tokens": getattr(usage_stats, "cached_tokens", 0),
                }

        data_to_save = {
            "result": result.final_result(),
            "success": result.is_successful(),
            "duration_seconds": result.total_duration_seconds(),
            "has_errors": result.has_errors(),
            "cost": cost_data,
            "usage": {
                "total_prompt_tokens": result.usage.total_prompt_tokens,
                "total_prompt_cached_tokens": result.usage.total_prompt_cached_tokens,
                "total_completion_tokens": result.usage.total_completion_tokens,
                "total_tokens": result.usage.total_tokens,
                "total_cost": result.usage.total_cost,
            },
        }

        # Save the result data to a JSON file
        import json

        result_filename = f"result_{int(time.time())}.json"
        with open(result_filename, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)

        print(f"🔍 Result saved to file: {result_filename}")

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

            if chrome_process:
                chrome_process.terminate()
                try:
                    await asyncio.wait_for(chrome_process.wait(), 5)
                except TimeoutError:
                    chrome_process.kill()

            if user_data_dir and os.path.exists(user_data_dir):
                shutil.rmtree(user_data_dir, ignore_errors=True)
        except Exception as cleanup_error:
            print(f"⚠️  Error closing playwright browser: {cleanup_error}")

        if file_path:
            cleanup_resume(file_path)

        print("✅ Cleanup complete")


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(start_agent())
