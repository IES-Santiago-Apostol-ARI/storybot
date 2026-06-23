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
from app.routers.capabilities import router as capabilities_router
from app.routers.generate import router as generate_router
from app.routers.generated import router as generated_router
from app.routers.printer import router as printer_router
from app.routers.wifi import router as wifi_router
from app.routers.bt import router as bt_router
from app.routers.updates import router as updates_router
from app.services.hardware_manager import HardwareManager
from app.services.story_manager import StoryManager
from app.services.story_generator import StoryGenerator
from app.services.swap_orchestrator import SwapOrchestrator
from app.services.capability_probe import probe_capability
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

    # D-07 / D-12 step 2: probe capability and set both attributes atomically.
    profile = probe_capability()
    app.state.capability = profile
    app.state.ai_enabled = profile.ai_enabled

    # D-12 step 3: AI services only when ai_enabled (D-09 — no stub, no None).
    if profile.ai_enabled:
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

    # D-08: overwrite capability.printer from probe default (False) to actual result.
    app.state.capability = app.state.capability.model_copy(
        update={
            "printer": app.state.printer is not None
            and not getattr(app.state.printer, "is_mock", True)
        }
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

    # Phase 23 D-06: boot-time update check (skip during testing).
    if not os.environ.get("TESTING"):
        try:
            from app.services.update_manager import create_update_manager

            update_mgr = create_update_manager()
            result = await asyncio.wait_for(
                update_mgr.check_update(), timeout=10
            )
            app.state.update_available = result.get("update_available", False)
            app.state.update_info = result
        except Exception as e:
            import json
            import sys

            print(
                json.dumps(
                    {
                        "event": "boot_update_check_failed",
                        "reason": type(e).__name__,
                    }
                ),
                file=sys.stderr,
            )
            app.state.update_available = False
            app.state.update_info = {}
    else:
        app.state.update_available = False
        app.state.update_info = {}

    # Initialize config
    _ = config.load()

    # Initialize hardware detection — D-15: pass ai_enabled explicitly.
    await hardware.detect_hardware(ai_enabled=profile.ai_enabled)

    # Phase 32 LED-06: construct the LedAnimator render engine on the
    # already-probed led driver and start its loop UNCONDITIONALLY (D-12 /
    # Pitfall 1 — NO TESTING guard, so the loop runs over MockLEDService in CI
    # and /led can route through the engine). The engine is the sole writer.
    led_animator_task = None
    try:
        from app.services.led_animator import LedAnimator

        app.state.led_animator = LedAnimator(hardware._services.get("led"))
        led_animator_task = asyncio.create_task(app.state.led_animator.run())
        # Expose the task on the engine for lifecycle observation (LED-06 test).
        app.state.led_animator._run_task = led_animator_task

        # Phase 33 D-10 / LED-18: arm the engine-internal boot sweep one-shot so
        # it exercises the SPI/MockLEDService path once on startup, then settles
        # to idle. The sweep is engine-internal; the lifespan only arms it.
        app.state.led_animator.set_mode("boot")

        # Phase 33 D-05 / LED-21: feed the idle-only health-beacon status sink.
        # Derive a "a hardware service is down" flag from HardwareManager status
        # (a service is down when its HardwareState.status == "error") and feed
        # it via set_health. The beacon's idle-only SUPPRESSION lives in the
        # engine (D-14) — the lifespan only supplies status.
        try:
            hw_status = await hardware.get_status()
            any_down = any(
                svc.get("status") == "error"
                for svc in hw_status.get("hardware", {}).values()
            )
            app.state.led_animator.set_health(down=any_down)
        except Exception as e:
            import json
            import sys

            print(
                json.dumps(
                    {
                        "event": "led_health_feed_failed",
                        "reason": type(e).__name__,
                    }
                ),
                file=sys.stderr,
            )
    except Exception as e:
        import json
        import sys

        print(
            json.dumps(
                {"event": "led_animator_init_failed", "reason": type(e).__name__}
            ),
            file=sys.stderr,
        )
        app.state.led_animator = None

    # Wire TTS pipeline to loaded engine (D-12 step 8: skip when ai disabled or testing)
    if profile.ai_enabled and not os.environ.get("TESTING"):
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

    # Phase 23 D-13: clear .update-state flag on successful boot.
    import json
    import sys

    flag_path = Path(".update-state")
    if flag_path.exists():
        flag_path.unlink(missing_ok=True)
        print(
            json.dumps({"event": "update_state_flag_cleared"}),
            file=sys.stderr,
        )

    # Phase 35 GPIO-05: register gpio service, create shared queue + task,
    # cancel on shutdown. Placed after led_animator, before bt_monitor.
    gpio_task = None
    try:
        from app.services.gpio_handler import create_gpio_service

        gpio_service = create_gpio_service()
        app.state.gpio_events = asyncio.Queue()  # shared; Phase 36 consumes
        await gpio_service.initialize(app.state.gpio_events)
        hardware.register_service("gpio", gpio_service)
        app.state.gpio_service = gpio_service
        gpio_task = asyncio.create_task(gpio_service.run(app.state.gpio_events))
        app.state.gpio_task = gpio_task
    except Exception as e:  # pragma: no cover — defensive; factory never raises
        print(
            json.dumps({"event": "gpio_init_failed", "reason": type(e).__name__}),
            file=sys.stderr,
        )

    # Phase 36 BTN-01/07: GpioDispatcher consumes from gpio_events and routes
    # to kiosk_events queue with debounce guard. Cancel on shutdown.
    gpio_dispatcher_task = None
    try:
        from app.services.gpio_dispatcher import GpioDispatcher

        app.state.kiosk_events = asyncio.Queue()
        app.state.gpio_dispatcher = GpioDispatcher(
            gpio_events=app.state.gpio_events,
            kiosk_events=app.state.kiosk_events,
            led_animator=getattr(app.state, "led_animator", None),
        )
        gpio_dispatcher_task = asyncio.create_task(
            app.state.gpio_dispatcher.run()
        )
        app.state.gpio_dispatcher_task = gpio_dispatcher_task
    except Exception as e:  # pragma: no cover — defensive
        print(
            json.dumps({"event": "gpio_dispatcher_init_failed", "reason": type(e).__name__}),
            file=sys.stderr,
        )

    # Phase 28 BOOT-04: start health monitor in background (skip during testing).
    bt_monitor_task = None
    if not os.environ.get("TESTING"):
        try:
            from app.services.bt_monitor import BtMonitor
            from app.services.bt_manager import create_bt_manager
            from app.services.bt_audio import route_to_wired

            app.state.bt_monitor = BtMonitor(
                manager=create_bt_manager(), route_to_wired=route_to_wired
            )
            bt_monitor_task = asyncio.create_task(app.state.bt_monitor.run())
        except Exception as e:
            print(
                json.dumps({"event": "bt_monitor_init_failed", "reason": type(e).__name__}),
                file=sys.stderr,
            )

    yield

    # Shutdown
    # Phase 32 LED-06 / CR-01: stop the animation loop BEFORE closing hardware.
    # The animator is a *continuous* ~30 FPS writer (unlike bt_monitor), so it
    # must be cancelled + gathered first; otherwise the loop keeps issuing SPI
    # writes against the device that hardware.shutdown() just closed and repaints
    # over the shutdown turn_off(), leaving the strip lit.
    if led_animator_task:
        led_animator_task.cancel()
        await asyncio.gather(led_animator_task, return_exceptions=True)

    # Phase 35 GPIO-05: cancel gpio background task before hardware shutdown.
    if gpio_task:
        gpio_task.cancel()
        await asyncio.gather(gpio_task, return_exceptions=True)

    # Phase 36 BTN-07: cancel gpio dispatcher before hardware shutdown.
    if gpio_dispatcher_task:
        gpio_dispatcher_task.cancel()
        await asyncio.gather(gpio_dispatcher_task, return_exceptions=True)

    await hardware.shutdown()

    # Phase 28 BOOT-04: clean cancel of health monitor.
    if bt_monitor_task:
        bt_monitor_task.cancel()
        await asyncio.gather(bt_monitor_task, return_exceptions=True)



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
app.include_router(capabilities_router)
app.include_router(generate_router, tags=["generate"])
app.include_router(generated_router)
app.include_router(printer_router)
app.include_router(wifi_router)
app.include_router(bt_router)
app.include_router(updates_router)

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
