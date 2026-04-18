from fastapi import APIRouter
from app.api.v1.endpoints.contributors import router as contributors_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(contributors_router)
