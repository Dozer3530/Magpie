"""FastAPI app for Magpie's local web frontend.

Every route is a thin shell over `app/services/*` — no domain logic lives
here. Mirrors the desktop tabs 1:1 so the two frontends stay in lockstep.

Security posture (single-user, local): bind 127.0.0.1 only, no auth. The
templates carry real client coordinates — never expose this server.
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import image_storage
from app.crops import CROPS
from app.db import init_db
from app.services import exports as exports_service
from app.services import imports as imports_service
from app.services import maintenance as maintenance_service
from app.services import observations as obs_service
from app.services import weeks as weeks_service
from app.services.imports import DuplicateTargetError
from webapp import serialize

# Uploaded import files live here until their commit re-reads them. The web
# flow is two-step (upload → preview → commit) like the desktop browse→import;
# we persist the file rather than holding parsed rows in memory, so a server
# restart between the two steps doesn't lose a half-finished import.
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "magpie_uploads"
_uploads: dict[str, Path] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    weeks_service.ensure_current_week()
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Magpie",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ---- Crops + weeks ---------------------------------------------------------

@app.get("/api/crops")
def get_crops() -> list[dict]:
    return [{"code": c.code, "display_name": c.display_name} for c in CROPS]


@app.get("/api/weeks")
def get_weeks() -> dict:
    return {
        "current": weeks_service.current_iso_week(),
        "weeks": weeks_service.list_week_rows(),
    }


class WeekCreate(BaseModel):
    tag: str
    label: str | None = None


@app.post("/api/weeks")
def post_week(body: WeekCreate) -> dict:
    weeks_service.create_week(body.tag, body.label)
    return {"ok": True, "tag": body.tag}


@app.delete("/api/weeks/{tag}")
def delete_week(tag: str) -> dict:
    weeks_service.delete_week(tag)
    return {"ok": True}


@app.get("/api/weeks/progress")
def get_weeks_progress() -> list[dict]:
    """Per-week, per-crop Field vs Lab completeness for the Weeks dashboard."""
    return weeks_service.all_weeks_progress()


class WeekRename(BaseModel):
    old: str
    new: str


@app.post("/api/weeks/rename")
def post_week_rename(body: WeekRename) -> dict:
    try:
        new_tag = weeks_service.rename_week(body.old, body.new)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "tag": new_tag}


@app.post("/api/backup")
def post_backup() -> dict:
    """Write a timestamped, consistent snapshot of packages.sqlite."""
    dest = maintenance_service.create_backup()
    return {"ok": True, "name": dest.name, "path": str(dest)}


# ---- Overview --------------------------------------------------------------

@app.get("/api/overview")
def get_overview(crop: str, week: str) -> dict:
    status = exports_service.week_status(crop, week)
    return serialize.week_status_dict(status)


# ---- Observations ----------------------------------------------------------

@app.get("/api/form-schema")
def get_form_schema(crop: str) -> dict:
    return serialize.form_schema_dict(obs_service.build_form_schema(crop))


@app.get("/api/obs")
def get_obs(crop: str, week: str, loc: str) -> dict:
    return {"values": obs_service.load(crop, week, loc)}


class ObsSave(BaseModel):
    crop: str
    week: str
    loc: str
    values: dict[str, str]


@app.put("/api/obs")
def put_obs(body: ObsSave) -> dict:
    obs_service.save(body.crop, body.week, body.loc, body.values)
    return {"ok": True}


# ---- Import: two-step (upload → commit) ------------------------------------

@app.post("/api/import/upload")
async def import_upload(crop: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Save the uploaded file, auto-map it, return a token + mapping preview.

    The token keys the temp file; the survey/lab commit routes re-load from it.
    """
    suffix = Path(file.filename or "upload").suffix or ".csv"
    token = uuid.uuid4().hex
    dest = _UPLOAD_DIR / f"{token}{suffix}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        loaded = imports_service.prepare(dest, crop)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}")
    _uploads[token] = dest
    preview = serialize.loaded_preview_dict(loaded)
    preview["token"] = token
    preview["filename"] = file.filename
    return preview


def _reload(token: str, crop: str):
    path = _uploads.get(token)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Upload expired — re-upload the file.")
    return imports_service.prepare(path, crop)


class SurveyCommit(BaseModel):
    token: str
    crop: str
    week: str
    id_col: str


@app.post("/api/import/survey")
def import_survey(body: SurveyCommit) -> dict:
    loaded = _reload(body.token, body.crop)
    res = imports_service.commit_survey(loaded, body.crop, body.week, body.id_col)
    return serialize.import_result_dict(res)


class LabCommit(BaseModel):
    token: str
    crop: str
    week: str
    # JSON object keys are strings; map source-row index → location_id.
    row_targets: dict[str, str]


@app.post("/api/import/lab")
def import_lab(body: LabCommit) -> dict:
    loaded = _reload(body.token, body.crop)
    row_targets = {int(k): v for k, v in body.row_targets.items()}
    try:
        res = imports_service.commit_lab(loaded, body.crop, body.week, row_targets)
    except DuplicateTargetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return serialize.import_result_dict(res)


# ---- Export ----------------------------------------------------------------

@app.post("/api/export")
def export_crop(crop: str, week: str) -> dict:
    return serialize.export_result_dict(exports_service.build_week_package(crop, week))


@app.post("/api/export-all")
def export_all(week: str) -> dict:
    return serialize.export_result_dict(exports_service.build_all(week))


@app.get("/api/export/{week}/download")
def export_download(week: str):
    zip_path = exports_service.week_dir(week) / f"EarthDaily_{week}.zip"
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="No package built for that week yet.")
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


# ---- Images ----------------------------------------------------------------

@app.get("/api/images")
def list_images(crop: str, week: str, loc: str) -> dict:
    return {"images": image_storage.list_existing(crop, week, loc)}


@app.get("/api/images/file")
def get_image(crop: str, week: str, loc: str, name: str):
    path = image_storage.absolute_path(crop, week, loc, name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(path)


@app.post("/api/images")
async def post_image(
    crop: str = Form(...),
    week: str = Form(...),
    loc: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    # attach() expects a real source file; stage the upload to a temp path.
    suffix = Path(file.filename or "img").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        stored = image_storage.attach(crop, week, loc, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"stored": stored}


# ---- Static frontend (served last so /api/* wins) --------------------------

_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
else:
    @app.get("/")
    def _no_frontend() -> JSONResponse:
        return JSONResponse(
            {"message": "Magpie API is running. The web frontend (webapp/static) "
                        "is not built yet — see /api/docs for the API."}
        )
