from typing import Annotated, Optional
from pydantic import BaseModel, EmailStr, ConfigDict, StringConstraints, field_validator
from app.models.user import UserRole

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True
    must_change_password: bool = False

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v):
        return str(v)

# Admin user-management: creating an account never takes a password from the caller --
# the server always generates one (see app.core.security.generate_temp_password).
class AdminUserCreate(BaseModel):
    full_name: str
    email: EmailStr
    department: Optional[str] = None
    role: UserRole

class TempPasswordResult(BaseModel):
    """The ONE-TIME response shown to the admin right after create/reset. This is the
    only place a plaintext password ever appears in any API response, and it is never
    persisted anywhere -- only its bcrypt hash is stored."""
    user: UserOut
    temporary_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class SetActiveRequest(BaseModel):
    is_active: bool


class AdminUserUpdate(BaseModel):
    """Admin edit of an existing account's profile. Only the fields sent are changed;
    email, password and active status have their own dedicated flows."""
    # Stripped, and must not be blank (a constraint rather than a raising validator, so
    # the 422 body stays plain JSON).
    full_name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]] = None
    department: Optional[str] = None
    role: Optional[UserRole] = None

    @field_validator("department")
    @classmethod
    def _trim_department(cls, v):
        # A blank department clears it (stored as NULL), same as on create.
        if v is None:
            return v
        v = v.strip()
        return v or None
