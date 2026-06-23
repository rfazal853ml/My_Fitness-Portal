from pydantic import BaseModel, field_validator
from typing import Optional


class PlanCreate(BaseModel):
    name:             str
    price:            float
    duration_days:    int
    gender:           str = "any"
    discount_percent: float = 0.0
    features:         list[str] = []
    is_active:        bool = True

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v):
        if v not in ("male", "female", "any"):
            raise ValueError("Gender must be male, female, or any")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Price cannot be negative")
        return round(v, 2)

    @field_validator("discount_percent")
    @classmethod
    def validate_discount(cls, v):
        if not (0 <= v <= 100):
            raise ValueError("Discount must be between 0 and 100")
        return round(v, 2)

    @field_validator("duration_days")
    @classmethod
    def validate_duration(cls, v):
        if v <= 0:
            raise ValueError("Duration must be at least 1 day")
        return v


class PlanUpdate(BaseModel):
    name:             Optional[str] = None
    price:            Optional[float] = None
    duration_days:    Optional[int] = None
    gender:           Optional[str] = None
    discount_percent: Optional[float] = None
    features:         Optional[list[str]] = None
    is_active:        Optional[bool] = None