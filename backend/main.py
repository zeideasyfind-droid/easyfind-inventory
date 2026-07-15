from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import catalog, extract, health, inventory, publish

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="EasyFind Inventory Engine")

app.include_router(health.router)
app.include_router(extract.router)
app.include_router(inventory.router)
app.include_router(publish.router)
app.include_router(catalog.router)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")
