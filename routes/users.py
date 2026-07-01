from fastapi import APIRouter, Depends, HTTPException
from typing import List, Annotated
from schemas.user import UserCreate, UserResponse
from services.user_service import UserService
from dependencies import get_user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    summary="Create a new user",
    description="Create a new user with business_id, name, location, service, and business_name"
)
async def create_user(
    user: UserCreate,
    user_service: Annotated[UserService, Depends(get_user_service)]
):
    existing_user = user_service.get_user_by_business_id(user.business_id)
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this business_id already exists")
    return user_service.create_user(user)


@router.get(
    "",
    response_model=List[UserResponse],
    summary="Get all users",
    description="Get a list of all users with pagination (skip and limit parameters)"
)
async def get_users(
    user_service: Annotated[UserService, Depends(get_user_service)],
    skip: int = 0,
    limit: int = 100
):
    return user_service.get_all_users(skip, limit)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a user by ID",
    description="Get a single user's information by their user ID"
)
async def get_user(
    user_id: int,
    user_service: Annotated[UserService, Depends(get_user_service)]
):
    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
