"""Upload-only local web API; no arbitrary filesystem access or persistence."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import __version__
from .scanner import MAX_ZIP_BYTES, ScanError, analyze_sources, analyze_zip

app = FastAPI(title="DependencyAtlas", version=__version__, description="Local-first static import graph inspector")
INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"

DEMO = {
    "shop/__init__.py": "",
    "shop/api.py": "from .services import checkout\n",
    "shop/services.py": "from .inventory import reserve\nfrom .api import router\n",
    "shop/inventory.py": "import json\ndef reserve(): return True\n",
    "shop/utils.py": "from .inventory import reserve\n",
}


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(INDEX_FILE)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/demo")
def demo():
    return analyze_sources(DEMO, "demo-shop")


@app.post("/api/analyze")
async def analyze_upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip archive of your Python project")
    try:
        raw = await file.read(MAX_ZIP_BYTES + 1)
        if len(raw) > MAX_ZIP_BYTES:
            raise HTTPException(status_code=413, detail="ZIP exceeds 8 MiB upload limit")
        return analyze_zip(raw, file.filename or "project.zip")
    except ScanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
