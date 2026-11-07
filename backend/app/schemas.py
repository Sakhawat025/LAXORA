from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
class Register(Input):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal['client', 'lawyer'] = 'client'
    phone: str = Field(default='', max_length=40)
    city: str = Field(default='', max_length=120)
    address: str = Field(default='', max_length=500)
class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    role: Literal['client', 'lawyer', 'admin'] | None = None
class Profile(Input):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default='', max_length=40)
    city: str = Field(default='', max_length=120)
    address: str = Field(default='', max_length=500)
    bio: str = Field(default='', max_length=3000)
class Password(Input):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
class LawyerProfile(Input):
    area_id: int | None = None
    biography: str = Field(default='', max_length=10000)
    education: str = Field(default='', max_length=2000)
    experience: int = Field(default=0, ge=0, le=80)
    jurisdiction: str = Field(default='', max_length=120)
    location: str = Field(default='', max_length=120)
    photo: str = Field(default='', max_length=500)
    @field_validator('photo')
    @classmethod
    def photo_url(cls, v):
        if v and not v.startswith('https://'): raise ValueError('Use an HTTPS photo URL')
        return v
class SlotInput(Input):
    starts_at: datetime
class Booking(Input):
    lawyer_id: int
    slot_id: int
    issue: str = Field(min_length=10, max_length=10000)
    contact: str = Field(min_length=3, max_length=200)
class BookingUpdate(Input):
    status: Literal['approved', 'rejected', 'cancelled', 'completed'] | None = None
    slot_id: int | None = None
class MessageInput(Input):
    body: str = Field(min_length=1, max_length=5000)
class Verification(Input):
    status: Literal['verified', 'rejected']
    note: str = Field(default='', max_length=2000)
class AdminUser(Input):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    active: bool | None = None
class ManualLawyer(Register):
    role: Literal['lawyer'] = 'lawyer'
    professional: LawyerProfile
class AreaInput(Input):
    name: str = Field(min_length=2, max_length=100)

class InviteInput(Input):
    email: EmailStr
class AdminRegister(Input):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    invite_code: str = Field(min_length=20, max_length=200)
class ConversationInput(Input):
    recipient_id: int
