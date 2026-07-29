from fastapi import APIRouter

from app.api.routes import (
    chat,
    customers,
    products,
    proposal,
    render,
    sessions,
    shop,
    tasks,
    upload,
)

api_router = APIRouter()
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(tasks.router, prefix="/design/tasks", tags=["design_tasks"])
api_router.include_router(chat.router, prefix="/design/chat", tags=["design_chat"])
api_router.include_router(render.router, prefix="/design/render", tags=["design_render"])
api_router.include_router(proposal.router, prefix="/design", tags=["design_proposal"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(shop.router, prefix="/shop", tags=["shop"])
