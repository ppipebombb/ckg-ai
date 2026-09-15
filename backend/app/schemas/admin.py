import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    created_at: datetime
    updated_at: datetime
