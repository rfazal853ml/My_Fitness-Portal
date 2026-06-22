from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginForm(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordForm(BaseModel):
    identifier: str  # email, phone, or CNIC


class OTPVerifyForm(BaseModel):
    otp: str
    user_id: str  # passed as hidden field


class ResetPasswordForm(BaseModel):
    new_password: str
    confirm_password: str
    user_id: str  # passed as hidden field
    otp_id: str   # passed as hidden field after OTP verified


class TokenData(BaseModel):
    user_id: str
    role: str
    name: str