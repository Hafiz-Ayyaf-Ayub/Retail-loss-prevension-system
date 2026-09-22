from fastapi import APIRouter
from app.camera import camera_stream
from app.detection import zone_monitor
from app.detection import concealment_monitor

router = APIRouter()


def _build_stats(cam_id: int):
    state = camera_stream._get_state(cam_id)
    is_running = state["capture"] is not None and state["capture"].isOpened()

    return {
        "camera_id": cam_id,
        "person_count": state["current_person_count"],
        "total_unique_visitors": len(state["unique_visitor_ids"]),
        "entry_count": state["entry_count"],
        "exit_count": state["exit_count"],
        "camera_active": is_running,
        "alerts": state["active_alerts"],
        "concealment_alerts": state["active_concealment_alerts"],
    }


@router.get("/stats")
def get_stats():
    data = _build_stats(cam_id=1)
    data["alert_history"] = zone_monitor.alert_history
    data["concealment_history"] = concealment_monitor.concealment_history
    return data


@router.get("/stats/{cam_id}")
def get_stats_by_id(cam_id: int):
    return _build_stats(cam_id=cam_id)


@router.get("/stats-all")
def get_stats_all():
    """Sab 4 cameras ki stats ek sath — Alerts box ke liye."""
    all_stats = [_build_stats(cam_id=i) for i in range(1, 5)]
    return {
        "cameras": all_stats,
        "alert_history": zone_monitor.alert_history,
        "concealment_history": concealment_monitor.concealment_history,
    }