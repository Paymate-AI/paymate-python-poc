from fastapi import APIRouter, Depends, HTTPException
from typing import List, Annotated
from schemas.business import BusinessResponse, BusinessCreate, BusinessUpdate
from services.business_service import BusinessService
from dependencies import get_business_service

router = APIRouter(prefix="/businesses", tags=["Businesses"])


@router.get(
    "",
    response_model=List[BusinessResponse],
    summary="Get all businesses",
    description="Get a list of all businesses with pagination"
)
async def get_businesses(
    business_service: Annotated[BusinessService, Depends(get_business_service)],
    skip: int = 0,
    limit: int = 100
):
    return await business_service.get_all_businesses(skip, limit)


@router.get(
    "/available",
    response_model=List[BusinessResponse],
    summary="Get available (active) businesses",
    description="Get a list of all active businesses with pagination"
)
async def get_available_businesses(
    business_service: Annotated[BusinessService, Depends(get_business_service)],
    skip: int = 0,
    limit: int = 100
):
    return await business_service.get_available_businesses(skip, limit)


@router.get(
    "/{business_id}",
    response_model=BusinessResponse,
    summary="Get a business by ID",
    description="Get a single business's information by their database ID"
)
async def get_business(
    business_id: int,
    business_service: Annotated[BusinessService, Depends(get_business_service)]
):
    business = await business_service.get_business_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get(
    "/business-id/{business_id}",
    response_model=BusinessResponse,
    summary="Get a business by business_id",
    description="Get a single business's information by their unique business UUID"
)
async def get_business_by_business_id(
    business_id: str,
    business_service: Annotated[BusinessService, Depends(get_business_service)]
):
    business = await business_service.get_business_by_business_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.get(
    "/user/{user_id}",
    response_model=BusinessResponse,
    summary="Get business by user ID",
    description="Get the business associated with a specific user"
)
async def get_business_by_user(
    user_id: int,
    business_service: Annotated[BusinessService, Depends(get_business_service)]
):
    business = await business_service.get_business_by_user_id(user_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found for this user")
    return business


@router.post(
    "/user/{user_id}",
    response_model=BusinessResponse,
    status_code=201,
    summary="Create a business for an existing user",
    description="Create a new business and link it to an existing user"
)
async def create_business_for_user(
    user_id: int,
    business: BusinessCreate,
    business_service: Annotated[BusinessService, Depends(get_business_service)]
):
    return await business_service.create_business(business, user_id)


@router.put(
    "/{business_id}",
    response_model=BusinessResponse,
    summary="Update a business",
    description="Update a business's information"
)
async def update_business(
    business_id: int,
    business: BusinessUpdate,
    business_service: Annotated[BusinessService, Depends(get_business_service)]
):
    updated_business = await business_service.update_business(business_id, business)
    if not updated_business:
        raise HTTPException(status_code=404, detail="Business not found")
    return updated_business
