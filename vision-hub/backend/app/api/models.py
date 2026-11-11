"""Model library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import ModelConfigOut, ModelDetailOut, ModelOut
from app.services import model_service

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelOut])
def list_models(category: str | None = Query(None), db: Session = Depends(get_db)):
    return model_service.list_models(db, category)


@router.get("/{model_id}", response_model=ModelDetailOut)
def get_model(model_id: str, db: Session = Depends(get_db)):
    return model_service.get_model(db, model_id)


@router.get("/{model_id}/configuration", response_model=ModelConfigOut)
def get_configuration(model_id: str):
    return model_service.get_configuration(model_id)
