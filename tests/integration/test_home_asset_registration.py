"""资产路由必须接入真实应用，不能只在隔离测试应用中存在。"""

from app.api.main import api_router


def test_home_asset_routes_registered():
    routes = {
        (route.path, method)
        for route in api_router.routes
        for method in getattr(route, "methods", set())
    }
    root = "/design/tasks/{task_id}/home-design"
    assert (root + "/asset-options", "GET") in routes
    assert (root + "/assets", "POST") in routes
    assert (root + "/assets/{asset_id}", "GET") in routes
