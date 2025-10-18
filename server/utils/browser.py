import asyncio
import os
import hmac
import hashlib
import time
from typing import Dict, Any, Optional

import aiofiles
import aiohttp
from dotenv import load_dotenv

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatBrowserUse

from anchorbrowser import Anchorbrowser

from .profile import default_profile
from .tools.playwright import playwright_tools, connect_playwright_to_cdp
from .resume import download_resume, cleanup_resume
from .prompt import default_prompt

load_dotenv()


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
    session_id: str,
    success: bool,
    agent_result: Dict[str, Any],
    cost_metadata: Dict[str, Any],
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
        "session_id": session_id,
        "success": success,
        "user_id": user_id,
        "agent_result": agent_result,
        "cost_metadata": cost_metadata,
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

    # Initialize Anchor client and create browser session
    anchor_client = Anchorbrowser(api_key=os.getenv("ANCHOR_API_KEY"))
    session = anchor_client.sessions.create(
        browser={"headless": {"active": False}},
    )

    session_id = session.data.id

    # Start the agent process in the background
    asyncio.create_task(
        _run_agent_background(
            anchor_client,
            session,
            user_id,
            url,
            profile,
            resume_url,
            instructions,
            secrets,
            webhook_url,
            session_id,
        )
    )

    # Return session_id immediately
    return session_id, session.data.live_view_url


async def _run_agent_background(
    anchor_client: Anchorbrowser,
    session: dict,
    user_id: str,
    url: str,
    profile: dict,
    resume_url: str,
    instructions: str,
    secrets: dict,
    webhook_url: Optional[str],
    session_id: str,
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

        # Connect Playwright to the browser
        playwright_connected = await connect_playwright_to_cdp(session.data.cdp_url)
        if not playwright_connected:
            raise Exception(
                "Failed to connect Playwright to browser. File uploads will not work."
            )

        browser_session = BrowserSession(
            cdp_url=session.data.cdp_url,
            headless=False,
            optimize_keyboard_events=True,
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

        result = await agent.run()

        # Prepare metadata for webhook
        agent_result = {
            "user_id": user_id,
            "url": url,
            "duration_seconds": result.total_duration_seconds(),
            "final_result": str(result.final_result()),
            "success": result.is_successful(),
            "has_errors": result.has_errors(),
        }

        cost_metadata = {
            "total_prompt_tokens": result.usage.total_prompt_tokens,
            "total_prompt_cached_tokens": result.usage.total_prompt_cached_tokens,
            "total_completion_tokens": result.usage.total_completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "total_cost": float(result.usage.total_cost)
            if result.usage.total_cost
            else "Unknown",
        }

        # Write the result to a file (prod_results/result_<timestamp>.json)
        import json

        # Check if the directory exists
        if not os.path.exists("prod_results"):
            # If it doesn't exist, create it
            os.makedirs("prod_results")

        with open(f"prod_results/result_{time.time()}.json", "w") as f:
            json.dump(
                {
                    "agent_result": agent_result,
                    "cost_metadata": cost_metadata,
                },
                f,
                indent=2,
            )

        # Send webhook notification
        await send_webhook(
            webhook_url,
            user_id,
            session_id,
            result.is_successful(),
            agent_result,
            cost_metadata,
        )

    except Exception as e:
        print(f"❌ Error: {e}")

        # Send webhook notification for failure
        error_metadata = {
            "error": str(e),
            "user_id": user_id,
            "url": url,
        }
        await send_webhook(webhook_url, user_id, session_id, False, error_metadata)
        raise

    finally:
        if anchor_client and session:
            anchor_client.sessions.delete(session.data.id)

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
        except Exception as cleanup_error:
            print(f"⚠️  Error closing playwright browser: {cleanup_error}")

        if file_path:
            cleanup_resume(file_path)

        if session:
            await anchor_download_replay(anchor_client, session.data.id)

        print("✅ Cleanup complete")


async def anchor_download_replay(anchor_client: Anchorbrowser, session_id: str):
    recordings = anchor_client.sessions.recordings.list(session_id)
    print("Recordings:", recordings.data)
    recording = anchor_client.sessions.recordings.primary.get(session_id)

    # Save to file
    with open(f"recording-{session_id}.mp4", "wb") as f:
        for chunk in recording.iter_bytes(chunk_size=8192):
            f.write(chunk)

    print(f"Recording saved as recording-{session_id}.mp4")


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(start_agent())
