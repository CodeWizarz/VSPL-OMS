import enum
import uuid
from sqlalchemy import Column, String, Boolean, Enum, DateTime
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CEO = "ceo"
    PRODUCTION_MANAGER = "production_manager"
    PLANNER = "planner"
    QA = "qa"
    DISPATCH = "dispatch"
    MACHINE_OPERATOR = "machine_operator"
    OPERATOR = "operator"
    PACKING = "packing"
    STORE = "store"
    SALES = "sales"
    DATA_ANALYST = "data_analyst"
    ENGINEERING = "engineering"
    MANUFACTURING = "manufacturing"

class User(Base):
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    secondary_role = Column(Enum(UserRole), nullable=True)
    employee_id = Column(String, nullable=True)
    department = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def has_any_role(self, *allowed_roles: UserRole) -> bool:
        """Returns True if either the user's primary role or secondary role matches allowed_roles."""
        user_roles = [self.role]
        if self.secondary_role:
            user_roles.append(self.secondary_role)
        allowed_values = {
            r.value.lower() if hasattr(r, "value") else str(r).lower()
            for r in allowed_roles
        }
        for r in user_roles:
            if r is None:
                continue
            if r in allowed_roles:
                return True
            r_str = (r.value if hasattr(r, "value") else str(r)).lower()
            if r_str in allowed_values:
                return True
        return False
