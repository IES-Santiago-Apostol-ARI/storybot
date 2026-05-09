"""StoryBot FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles wrapper that adds Cache-Control headers for media files."""

    async def get_response(self, path: str, scope) -> Response:
        """Get response with Cache-Control headers for audio files."""
        response = await super().get_response(path, scope)

        # Add no-cache headers for audio and image files
        if path.endswith(
            (".mp3", ".wav", ".m4a", ".ogg", ".jpg", ".jpeg", ".png", ".webp")
        ):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        return response


from app.config import ConfigManager
from app.routers.nfc import router as nfc_router
from app.routers.stories import router as stories_router
from app.routers.system import router as system_router
from app.routers.cards import router as cards_router
from app.routers.generate import router as generate_router
from app.services.hardware_manager import HardwareManager
from app.services.story_manager import StoryManager
from app.services.story_generator import StoryGenerator
from app.services.swap_orchestrator import SwapOrchestrator
from app.services.tts_pipeline import TTSPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Initialize hardware manager, config, and story manager on startup.
    Shutdown services on shutdown.
    """
    import os

    # Startup
    hardware = HardwareManager()
    config = ConfigManager()
    story_manager = StoryManager()

    # Store in app state
    app.state.hardware = hardware
    app.state.config = config
    app.state.story_manager = story_manager
    app.state.story_generator = StoryGenerator()
    app.state.swap_orchestrator = SwapOrchestrator()

    # Phase 16 D-18: attach printer service for /api/printer/print (router added in 16-04).
    try:
        from app.services.printer_handler import create_printer_service

        app.state.printer = create_printer_service()
    except (
        Exception
    ) as e:  # pragma: no cover — defensive; factory is contracted to never raise
        import json
        import sys

        print(
            json.dumps({"event": "printer_init_failed", "reason": type(e).__name__}),
            file=sys.stderr,
        )

    # Phase 16 D-13: 7-day disk hygiene for content/generated/<uuid>/.
    import asyncio

    try:
        from app.services.generated_sweeper import sweep_generated

        n = await asyncio.to_thread(sweep_generated, story_manager)
    except Exception as e:
        import json
        import sys

        print(
            json.dumps({"event": "sweep_failed", "reason": type(e).__name__}),
            file=sys.stderr,
        )

    # Initialize config
    _ = config.load()

    # Initialize hardware detection (stub for now)
    await hardware.detect_hardware()

    # Wire TTS pipeline to loaded engine (skip during testing)
    if not os.environ.get("TESTING"):
        tts_engine = hardware._services.get("tts")
        if tts_engine:
            app.state.tts_pipeline = TTSPipeline(synthesizer=tts_engine)

    # Ensure content directory exists (skip during testing)
    if not os.environ.get("TESTING"):
        content_dir = Path("content/stories")
        content_dir.mkdir(parents=True, exist_ok=True)

        # Ensure stories index exists
        index_file = content_dir / "stories.json"
        if not index_file.exists():
            import json

            index_file.write_text(
                json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
            )

    yield

    # Shutdown
    await hardware.shutdown()


app = FastAPI(
    title="StoryBot",
    description="Storytelling robot for children",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Redirect root to children's kiosk interface."""
    return RedirectResponse(url="/children/")


# Include routers
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(nfc_router)
app.include_router(stories_router)
app.include_router(cards_router)
app.include_router(generate_router, tags=["generate"])

# Mount static files for story content (with no-cache for audio)
stories_static_dir = Path("content/stories")
if stories_static_dir.exists():
    app.mount(
        "/static/stories",
        NoCacheStaticFiles(directory=str(stories_static_dir)),
        name="stories",
    )

# Mount static files for generated content (with no-cache for audio)
generated_static_dir = Path("content/generated")
if generated_static_dir.exists():
    app.mount(
        "/static/generated",
        NoCacheStaticFiles(directory=str(generated_static_dir)),
        name="generated",
    )

# Mount children's kiosk interface
children_static_dir = Path("static/children")
if children_static_dir.exists():
    app.mount(
        "/children",
        StaticFiles(directory=str(children_static_dir), html=True),
        name="children",
    )

# Mount admin panel (html=True enables index.html serving)
admin_static_dir = Path("static/admin")
if admin_static_dir.exists():
    app.mount(
        "/admin", StaticFiles(directory=str(admin_static_dir), html=True), name="admin"
    )

# Mount shared theme directory
shared_static_dir = Path("static/shared")
if shared_static_dir.exists():
    app.mount("/shared", StaticFiles(directory=str(shared_static_dir)), name="shared")
