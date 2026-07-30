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
    assert ("/api/design/tasks", "POST") in routes
    assert ("/api/design/chat", "POST") in routes
    assert ("/api/design/render", "POST") in routes
    assert ("/api/design/proposal-pdf", "POST") in routes
