from fastapi import APIRouter, Depends, HTTPException
from typing import List, Annotated
from schemas.product import ProductCreate, ProductUpdate, ProductResponse
from services.product_service import ProductService
from dependencies import get_product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.post("", response_model=ProductResponse, status_code=201)
async def create_product(
    product: ProductCreate,
    product_service: Annotated[ProductService, Depends(get_product_service)]
):
    return product_service.create_product(product)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    product_service: Annotated[ProductService, Depends(get_product_service)]
):
    product = product_service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/business/{business_id}", response_model=List[ProductResponse])
async def get_products_by_business(
    product_service: Annotated[ProductService, Depends(get_product_service)],
    business_id: str,
    skip: int = 0,
    limit: int = 100
):
    return product_service.get_products_by_business(business_id, skip, limit)


@router.get("/business/{business_id}/available", response_model=List[ProductResponse])
async def get_available_products(
    product_service: Annotated[ProductService, Depends(get_product_service)],
    business_id: str,
    skip: int = 0,
    limit: int = 100
):
    return product_service.get_available_products(business_id, skip, limit)


@router.get("/business/{business_id}/out-of-stock", response_model=List[ProductResponse])
async def get_out_of_stock_products(
    product_service: Annotated[ProductService, Depends(get_product_service)],
    business_id: str,
    skip: int = 0,
    limit: int = 100
):
    return product_service.get_out_of_stock_products(business_id, skip, limit)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_service: Annotated[ProductService, Depends(get_product_service)],
    product_id: int,
    product: ProductUpdate,
):
    updated_product = product_service.update_product(product_id, product)
    if not updated_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return updated_product
