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
    QUALITY = "quality"
    DISPATCH = "dispatch"
    MACHINE_OPERATOR = "machine_operator"
    OPERATOR = "operator"
    PACKING = "packing"
    STORE = "store"
    SALES = "sales"
    SUPERVISOR = "supervisor"   # shop-floor supervisor: production entry + movement only
    ACCOUNTS = "accounts"       # records customer payments against invoices
    DATA_ANALYST = "data_analyst"
    ENGINEERING = "engineering"
    MANUFACTURING = "manufacturing"

    # Stage roles: a Supervisor and a Manager for each of F1, F2, F3, SP, FI, Packing
    # and Dispatch. The stage is
    # part of the role, so the backend limits these users to posting at that stage
    # (app/core/departments.py). Supervisor: record production + move material at own
    # stage. Manager: the same, sees every stage, and edits own-stage plan dates.
    F1_SUPERVISOR = "f1_supervisor"
    F1_MANAGER = "f1_manager"
    F2_SUPERVISOR = "f2_supervisor"
    F2_MANAGER = "f2_manager"
    F3_SUPERVISOR = "f3_supervisor"
    F3_MANAGER = "f3_manager"
    SP_SUPERVISOR = "sp_supervisor"
    SP_MANAGER = "sp_manager"
    FI_SUPERVISOR = "fi_supervisor"
    FI_MANAGER = "fi_manager"
    PACKING_SUPERVISOR = "packing_supervisor"
    PACKING_MANAGER = "packing_manager"
    DISPATCH_SUPERVISOR = "dispatch_supervisor"
    DISPATCH_MANAGER = "dispatch_manager"

    # Supply Chain Manager (SCM): sends material to vendors and receives it back (Vendor
    # Tracking, Production Entry "At vendor"), and manages the Dispatch Center (packing,
    # BSR, dispatch). Not a stage role: no stage lock, and no in-house production entry.
    SCM = "scm"

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
        # CEO has full Admin access: wherever ADMIN is allowed, CEO is too.
        if "admin" in allowed_values:
            allowed_values.add("ceo")
        for r in user_roles:
            if r is None:
                continue
            if r in allowed_roles:
                return True
            r_str = (r.value if hasattr(r, "value") else str(r)).lower()
            if r_str in allowed_values:
                return True
        return False
