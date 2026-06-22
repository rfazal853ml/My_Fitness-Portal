from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    name:     str
    email:    EmailStr
    phone:    Optional[str] = None
    cnic:     Optional[str] = None
    address:  Optional[str] = None
    role_id:  str
    photo_url: Optional[str] = None


class UserUpdate(BaseModel):
    name:     Optional[str] = None
    email:    Optional[EmailStr] = None
    phone:    Optional[str] = None
    cnic:     Optional[str] = None
    address:  Optional[str] = None
    role_id:  Optional[str] = None
    is_active: Optional[bool] = None


class RoleCreate(BaseModel):
    name:           str
    description:    Optional[str] = None
    permission_ids: list[str] = []


class RoleUpdate(BaseModel):
    name:           Optional[str] = None
    description:    Optional[str] = None
    permission_ids: list[str] = []