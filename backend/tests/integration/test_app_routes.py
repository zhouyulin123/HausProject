import pytest

from app.main import app


@pytest.mark.integration
def test_core_customer_routes_are_registered():
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/sessions", "POST") in routes
    assert ("/api/upload/image", "POST") in routes
    assert ("/api/upload/images/{image_id}/room-model", "PUT") in routes
    assert ("/api/design/tasks", "POST") in routes
    assert ("/api/design/tasks/mine", "GET") in routes
    assert ("/api/design/tasks/{task_id}/plans/{plan_id}/refine", "POST") in routes
    assert ("/api/design/chat", "POST") in routes
    assert ("/api/design/render", "POST") in routes
    assert ("/api/design/proposal-pdf", "POST") in routes
    assert ("/api/design/plan-versions/{plan_version_id}/scene", "POST") in routes
    assert ("/api/design/plan-versions/{plan_version_id}/scene", "GET") in routes
    assert ("/api/design/plan-versions/{plan_version_id}/auto-layout", "POST") in routes
    assert ("/api/design/plan-versions/{plan_version_id}", "GET") in routes
    assert ("/api/design/scenes/{scene_id}", "GET") in routes
    assert ("/api/design/scenes/{scene_id}", "PUT") in routes
    assert ("/api/auth/send-code", "POST") in routes
    assert ("/api/auth/login", "POST") in routes
    assert ("/api/auth/me", "GET") in routes
    assert ("/api/orders", "POST") in routes
    assert ("/api/orders", "GET") in routes
    assert ("/api/orders/mine", "GET") in routes
    assert ("/api/orders/unread-count", "GET") in routes
    assert ("/api/orders/{order_id}", "GET") in routes
    assert ("/api/orders/{order_id}/quotes", "POST") in routes
    assert ("/api/orders/{order_id}/accept", "POST") in routes
    assert ("/api/orders/{order_id}/close", "POST") in routes
    assert ("/api/admin/users", "GET") in routes
    assert ("/api/admin/users/{user_id}/role", "PATCH") in routes
