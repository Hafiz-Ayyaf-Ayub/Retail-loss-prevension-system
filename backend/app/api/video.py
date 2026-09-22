from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.camera.camera_stream import (
    generate_frames,
    start_camera,
    stop_camera,
    pause_camera,
    resume_camera,
    set_zone,
    set_zone_enabled,
)

router = APIRouter()


class ZoneUpdate(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class ZoneToggle(BaseModel):
    enabled: bool


@router.get("/video-feed")
def video_feed():
    return StreamingResponse(
        generate_frames(cam_id=1),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/video-feed/{cam_id}")
def video_feed_by_id(cam_id: int):
    return StreamingResponse(
        generate_frames(cam_id=cam_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.post("/camera/start")
def camera_start():
    success = start_camera(cam_id=1)
    return {"status": "started" if success else "failed"}


@router.post("/camera/start/{cam_id}")
def camera_start_by_id(cam_id: int, device_index: int = 0):
    success = start_camera(cam_id=cam_id, device_index=device_index)
    return {"status": "started" if success else "failed"}


@router.post("/camera/pause")
def camera_pause():
    pause_camera(cam_id=1)
    return {"status": "paused"}


@router.post("/camera/pause/{cam_id}")
def camera_pause_by_id(cam_id: int):
    pause_camera(cam_id=cam_id)
    return {"status": "paused"}


@router.post("/camera/resume")
def camera_resume():
    resume_camera(cam_id=1)
    return {"status": "resumed"}


@router.post("/camera/resume/{cam_id}")
def camera_resume_by_id(cam_id: int):
    resume_camera(cam_id=cam_id)
    return {"status": "resumed"}


@router.post("/camera/stop")
def camera_stop():
    stop_camera(cam_id=1)
    return {"status": "stopped"}


@router.post("/camera/stop/{cam_id}")
def camera_stop_by_id(cam_id: int):
    stop_camera(cam_id=cam_id)
    return {"status": "stopped"}


@router.post("/camera/zone/{cam_id}")
def camera_zone_update(cam_id: int, zone: ZoneUpdate):
    """Frontend se naye zone coordinates (0.0 - 1.0 ratios) receive karke save karta hai."""
    set_zone(cam_id, zone.x1, zone.y1, zone.x2, zone.y2)
    return {"status": "zone_updated"}


@router.post("/camera/zone/{cam_id}/toggle")
def camera_zone_toggle(cam_id: int, toggle: ZoneToggle):
    """Zone ko is camera ke liye on/off karta hai."""
    set_zone_enabled(cam_id, toggle.enabled)
    return {"status": "zone_enabled" if toggle.enabled else "zone_disabled"}