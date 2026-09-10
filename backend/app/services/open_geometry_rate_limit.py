"""开放几何入口共享的任务级限流实例。"""

from app.core.config import settings
from app.services.scene_agent_rate_limit import SceneAgentRateLimiter


open_geometry_rate_limiter = SceneAgentRateLimiter(
    max_requests=settings.scene_agent_requests_per_minute,
    window_seconds=60,
)


def open_geometry_rate_key(task_id: int) -> str:
    return f"task:{task_id}"
