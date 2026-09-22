import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import Settings
from app.api.video import router as video_router
from app.api.stats import router as stats_router

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(title=Settings.APP_NAME, version=Settings.APP_VERSION)

app.include_router(video_router)
app.include_router(stats_router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))