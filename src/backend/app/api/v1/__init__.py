from fastapi import APIRouter

from app.api.v1 import auth, business, conversations, events, menu, orders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(business.router)
api_router.include_router(menu.router)
api_router.include_router(orders.router)
api_router.include_router(conversations.router)
api_router.include_router(events.router)
