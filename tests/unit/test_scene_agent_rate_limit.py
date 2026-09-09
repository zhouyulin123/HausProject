from app.services.scene_agent_rate_limit import SceneAgentRateLimiter


def test_scene_agent_rate_limiter_blocks_only_within_same_window():
    limiter = SceneAgentRateLimiter(max_requests=2, window_seconds=60)

    assert limiter.retry_after("session-a", now=100.0) is None
    assert limiter.retry_after("session-a", now=110.0) is None
    assert limiter.retry_after("session-b", now=111.0) is None

    retry_after = limiter.retry_after("session-a", now=120.0)
    assert retry_after == 40

    assert limiter.retry_after("session-a", now=161.0) is None


def test_scene_agent_rate_limiter_does_not_consume_blocked_requests():
    limiter = SceneAgentRateLimiter(max_requests=1, window_seconds=30)

    assert limiter.retry_after("session-a", now=10.0) is None
    assert limiter.retry_after("session-a", now=20.0) == 20
    assert limiter.retry_after("session-a", now=25.0) == 15
