from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date


class MemberCreate(BaseModel):
    full_name: str
    father_name: Optional[str] = None
    age: Optional[int] = None
    date_of_birth: Optional[str] = None
    cnic: str
    guardian_cnic: str
    phone: str
    gender: Optional[str] = None        # 'male' | 'female' | 'other'
    blood_group: Optional[str] = None
    email: Optional[str] = None
    joining_date: Optional[str] = None
    health_issues: Optional[List[str]] = []
    address: Optional[str] = None
    admission_fee: Optional[float] = 0.0
    discount_percent: Optional[float] = 0.0
    photo_url: Optional[str] = None
    # Membership
    plan_id: Optional[str] = None
    membership_start: Optional[str] = None
    membership_expiry: Optional[str] = None
    # Note
    note_title: Optional[str] = None
    note_description: Optional[str] = None


class MemberUpdate(BaseModel):
    full_name: Optional[str] = None
    father_name: Optional[str] = None
    age: Optional[int] = None
    date_of_birth: Optional[str] = None
    cnic: str
    guardian_cnic: str
    phone: Optional[str] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    email: Optional[str] = None
    joining_date: Optional[str] = None
    health_issues: Optional[List[str]] = None
    address: Optional[str] = None
    admission_fee: Optional[float] = None
    discount_percent: Optional[float] = None
    photo_url: Optional[str] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None
    plan_id: Optional[str] = None
    membership_start: Optional[str] = None
    membership_expiry: Optional[str] = None
    note_title: Optional[str] = None
    note_description: Optional[str] = None