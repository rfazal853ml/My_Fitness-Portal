from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse

from config import get_settings
from routers import auth
from routers import users as users_router
from routers import plans as plans_router
from utils.dependencies import get_current_user
from services.storage_service import StorageService

settings = get_settings()
templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🚀 {settings.app_name} starting...")
    # Initialize Supabase Storage buckets
    await StorageService.ensure_bucket_exists()
    yield
    print("👋 Shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    # Static files
    app.mount("/static", StaticFiles(directory="static"), name="static")

    # Routers
    app.include_router(auth.router)
    app.include_router(users_router.router)
    app.include_router(plans_router.router)

    # Root redirect → login
    @app.get("/")
    async def root():
        return RedirectResponse(url="/auth/login", status_code=302)

    # Dashboard (placeholder until we build it properly)
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ):
        from services.supabase_client import get_supabase
        db = get_supabase()
        gym_name_result = db.table("settings").select("value").eq("key", "gym_name").single().execute()
        gym_name = gym_name_result.data["value"] if gym_name_result.data else settings.app_name

        return templates.TemplateResponse(request, "dashboard/index.html", {
            "gym_name":    gym_name,
            "page_title":  "Dashboard",
            "active_page": "dashboard",
            "user":        current_user,
        })

    return app


app = create_app()