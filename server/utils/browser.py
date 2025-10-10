import asyncio
import os

import aiofiles
from dotenv import load_dotenv

from browser_use import Agent, BrowserSession
from browser_use.llm import ChatBrowserUse
from browser_use.tokens.service import TokenCost

from kernel import AsyncKernel, Kernel

from utils.profile import default_profile
from utils.tools.playwright import playwright_tools, connect_playwright_to_cdp
from utils.resume import download_resume, cleanup_resume
from utils.prompt import default_prompt

load_dotenv()


async def start_agent(
    user_id: str,
    url: str,
    profile: dict = default_profile,
    resume_url: str = "",
    instructions: str = "",
    secrets: dict = {},
):
    """
    Main function demonstrating Browser-Use + Playwright integration with custom actions.
    """
    if not user_id:
        raise ValueError("User ID is required")

    if not url:
        raise ValueError("URL is required")

    if not profile:
        raise ValueError("Profile is required")

    if not resume_url:
        raise ValueError("Resume URL or file path is required")

    if resume_url:
        # The resume url will always be from usfs, so we can safely download it
        file_path = download_resume(resume_url)

    prompt = default_prompt(url, profile, file_path, instructions)

    try:
        client = None
        kernel_browser = None
        replay = None

        # Initialize Kernel client
        client = Kernel(api_key=os.environ["KERNEL_API_KEY"])

        # try:
        #     await client.profiles.create(name=user_id)
        # except ConflictError:
        #     pass

        kernel_browser = client.browsers.create(
            # profile={
            #     "id": user_id,
            #     "save_changes": True,
            # }
        )

        # if kernel_browser.session_id:
        #     replay = client.browsers.replays.start(kernel_browser.session_id)

        print(f"Kernel browser URL: {kernel_browser.browser_live_view_url}")

        # Connect Playwright to the browser
        playwright_connected = await connect_playwright_to_cdp(
            kernel_browser.cdp_ws_url
        )
        if not playwright_connected:
            raise Exception(
                "Failed to connect Playwright to browser. File uploads will not work."
            )

        browser_session = BrowserSession(
            cdp_url=kernel_browser.cdp_ws_url,
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

        # TODO: Use metadata for webhook to update DB, send result to user via email
        metadata = {  # noqa: F841
            "usage_summary": usage_summary,
            "total_prompt_tokens": usage_summary.total_prompt_tokens,
            "total_prompt_cached_tokens": usage_summary.total_prompt_cached_tokens,
            "total_completion_tokens": usage_summary.total_completion_tokens,
            "total_tokens": usage_summary.total_tokens,
            "total_cost": usage_summary.total_cost,
            # TODO: add duration and result data (final step and success status)
        }

        print(f"✅ Integration demo completed! Result: {result}")

        # TODO: webhook to update DB, send result to user via email
        # TODO: webhook to add metadata such as price / duration / etc.

    except Exception as e:
        print(f"❌ Error: {e}")
        raise

    finally:
        if client and kernel_browser:
            client.browsers.delete_by_id(kernel_browser.session_id)
            if replay:
                client.browsers.replays.stop(
                    replay_id=replay.replay_id, id=kernel_browser.session_id
                )

        # Close playwright browser
        try:
            import utils.tools.playwright as playwright_module

            if playwright_module.playwright_browser:
                print("🔍 Closing playwright browser")
                await playwright_module.playwright_browser.close()
                playwright_module.playwright_browser = None
                playwright_module.playwright_page = None
        except Exception as cleanup_error:
            print(f"⚠️  Error closing playwright browser: {cleanup_error}")

        if file_path:
            cleanup_resume(file_path)

        # if client and kernel_browser and replay:
        #     await download_replay(client, kernel_browser)

        print("✅ Cleanup complete")


async def download_replay(client: AsyncKernel, kernel_browser):
    replays = client.browsers.replays.list(kernel_browser.session_id)

    for replay in replays:
        print(f"Replay ID: {replay.replay_id}")
        print(f"View URL: {replay.replay_view_url}")

        # Download the mp4 file
        video_data = client.browsers.replays.download(
            replay_id=replay.replay_id, id=kernel_browser.session_id
        )

        # Get the content as bytes
        content = video_data.read()

        if not os.path.exists("replays"):
            os.makedirs("replays")

        filename = f"replays/replay-{replay.replay_id}-{kernel_browser.session_id}.mp4"
        async with aiofiles.open(filename, "wb") as f:
            await f.write(content)

        print(f"Saved replay to {filename}")


if __name__ == "__main__":
    # Run the advanced integration demo
    asyncio.run(start_agent())
