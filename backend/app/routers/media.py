import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import current_teacher
from ..config import get_settings
from ..db import get_session
from ..media import MAX_BYTES, BadImage, process_image, store
from ..models import Media, Teacher

router = APIRouter(tags=["media"])


@router.post("/media")
async def upload(file: UploadFile = File(...), t: Teacher = Depends(current_teacher), s: AsyncSession = Depends(get_session)):
    data = await file.read(MAX_BYTES + 1)
    try:
        img, w, h = process_image(data)
    except BadImage as e:
        raise HTTPException(400, str(e)) from e
    mid, path = store(get_settings().media_dir, img)
    s.add(Media(id=mid, owner_id=t.id, path=path, width=w, height=h, bytes=len(img)))
    return {"id": str(mid), "url": f"/api/media/{mid}.webp", "width": w, "height": h}


@router.get("/media/{name}")
async def serve(name: str, s: AsyncSession = Depends(get_session)):
    if not name.endswith(".webp"):
        raise HTTPException(404)
    try:
        mid = uuid.UUID(name[:-5])
    except ValueError:
        raise HTTPException(404) from None
    m = await s.get(Media, mid)
    if not m or not os.path.exists(m.path):
        raise HTTPException(404)
    return FileResponse(
        m.path,
        media_type="image/webp",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=86400"},
    )
