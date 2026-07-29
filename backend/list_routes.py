from app.main import app

for route in app.routes:
    # Handle API routers
    if hasattr(route, "path"):
        print(f"Path: {route.path}, Name: {route.name}, Methods: {getattr(route, 'methods', 'N/A')}")
    if hasattr(route, "routes"):
        for sub_route in route.routes:
             print(f"Path: {sub_route.path}, Name: {sub_route.name}, Methods: {getattr(sub_route, 'methods', 'N/A')}")
