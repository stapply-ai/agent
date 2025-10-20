import asyncio
import os
import hmac
import hashlib
import time
import subprocess
import shutil
import tempfile
from typing import Dict, Any, Optional

import aiohttp
from dotenv import load_dotenv

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatBrowserUse

from anchorbrowser import Anchorbrowser

from .profile import default_profile
from .tools.playwright import playwright_tools, connect_playwright_to_cdp
from .resume import download_resume, cleanup_resume
from .prompt import default_prompt

import boto3

load_dotenv()

ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")  # e.g. 'abc123def4567890'
R2_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
R2_BUCKET = "recordings"


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
            from .tools.playwright import playwright_browser

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
            await anchor_download_replay(anchor_client, user_id, session.data.id)

        print("✅ Cleanup complete")


async def anchor_download_replay(
    anchor_client: Anchorbrowser, user_id: str, session_id: str
):
    """
    Downloads the session recording, trims the first 5 seconds, speeds it up 4x,
    and uploads the processed clip into R2. Returns the R2 object key:
    '{user_id}/{session_id}.mp4'
    """
    recording = anchor_client.sessions.recordings.primary.get(session_id)
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )

    key = f"{user_id}/{session_id}.mp4"
    content_type = "video/mp4"

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg is required to process recordings. Please install ffmpeg and ensure it is on PATH."
        )

    CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB

    with tempfile.TemporaryDirectory(prefix="stapply-recording-") as temp_dir:
        original_path = os.path.join(temp_dir, "original.mp4")
        processed_path = os.path.join(temp_dir, "processed.mp4")

        await asyncio.to_thread(
            _write_recording_to_file,
            recording,
            original_path,
            CHUNK_SIZE,
        )

        await asyncio.to_thread(
            _process_recording_with_ffmpeg,
            ffmpeg_path,
            original_path,
            processed_path,
        )

        init = await asyncio.to_thread(
            s3.create_multipart_upload,
            Bucket=R2_BUCKET,
            Key=key,
            ContentType=content_type,
            Metadata={"user_id": user_id, "session_id": session_id},
        )
        upload_id = init["UploadId"]

        parts = []
        part_number = 1

        try:
            with open(processed_path, "rb") as processed_file:
                while True:
                    chunk = processed_file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    resp = await asyncio.to_thread(
                        s3.upload_part,
                        Bucket=R2_BUCKET,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=chunk,
                    )
                    parts.append({"ETag": resp["ETag"], "PartNumber": part_number})
                    part_number += 1

            await asyncio.to_thread(
                s3.complete_multipart_upload,
                Bucket=R2_BUCKET,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

            print(f"Uploaded processed recording to R2 as s3://{R2_BUCKET}/{key}")
            return key

        except Exception as e:
            try:
                await asyncio.to_thread(
                    s3.abort_multipart_upload,
                    Bucket=R2_BUCKET,
                    Key=key,
                    UploadId=upload_id,
                )
            except Exception:
                pass
            raise e


def _write_recording_to_file(recording, destination: str, chunk_size: int) -> None:
    with open(destination, "wb") as output_file:
        for chunk in recording.iter_bytes(chunk_size=chunk_size):
            output_file.write(chunk)


def _process_recording_with_ffmpeg(
    ffmpeg_path: str, source: str, destination: str
) -> None:
    base_command = [
        ffmpeg_path,
        "-y",
        "-ss",
        "5",
        "-i",
        source,
        "-vf",
        "setpts=0.25*PTS",
        "-af",
        "atempo=2,atempo=2",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        destination,
    ]

    try:
        subprocess.run(
            base_command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if "matches no streams" in (exc.stderr or ""):
            fallback_command = [
                ffmpeg_path,
                "-y",
                "-ss",
                "5",
                "-i",
                source,
                "-vf",
                "setpts=0.25*PTS",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-movflags",
                "+faststart",
                destination,
            ]
            subprocess.run(
                fallback_command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return

        raise RuntimeError(
            f"ffmpeg failed while processing recording: {(exc.stderr or '').strip()}"
        ) from exc


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(start_agent())
