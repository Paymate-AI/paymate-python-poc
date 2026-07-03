from fastapi import APIRouter, Depends, HTTPException
from typing import List, Annotated
from schemas.user import UserResponse, UserWithBusinessCreate
from services.user_service import UserService
from dependencies import get_user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "/with-business",
    response_model=UserResponse,
    status_code=201,
    summary="Create a new user with a business",
    description="Create a new user and their associated business in one request"
)
async def create_user_with_business(
    data: UserWithBusinessCreate,
    user_service: Annotated[UserService, Depends(get_user_service)]
):
    return user_service.create_user_with_business(data)


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    summary="Create a new user (without business)",
    description="Create a new user with name and phone (business will need to be created separately"
)
async def create_user(
    user: "UserCreate",
    user_service: Annotated[UserService, Depends(get_user_service)]
):
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
    limit: int = 10
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


# Import UserCreate at the bottom to avoid circular imports
from schemas.user import UserCreate

