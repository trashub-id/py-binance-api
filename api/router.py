from fastapi import APIRouter
from api.routes import system
from api import wallet_routes, order_routes

api_router = APIRouter()

api_router.include_router(system.router)
api_router.include_router(wallet_routes.router)
api_router.include_router(order_routes.router)
