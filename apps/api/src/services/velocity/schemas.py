from enum import Enum
from pydantic import BaseModel, field_validator


class TicketType(str, Enum):
    STORY = "story"
    BUG = "bug"
    TASK = "task"


class Domain(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    INFRA = "infra"


# --- Inputs ---

class TicketRecord(BaseModel):
    """One completed ticket. sprint_id groups tickets into sprints."""
    developer_id: str
    ticket_type: TicketType
    domain: Domain
    story_points: float
    sprint_id: str

    @field_validator("story_points")
    @classmethod
    def points_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("story_points must be non-negative")
        return v


class SprintMeta(BaseModel):
    """Calendar facts about a sprint."""
    total_working_days: int
    team_members: list[str]

    @field_validator("total_working_days")
    @classmethod
    def days_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("total_working_days must be positive")
        return v


class PtoEntry(BaseModel):
    """Days off for one developer in the sprint."""
    developer_id: str
    days_off: float

    @field_validator("days_off")
    @classmethod
    def days_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("days_off must be non-negative")
        return v


class MeetingOverhead(BaseModel):
    """Recurring meeting hours per day for one developer (manual input, MVP)."""
    developer_id: str
    hours_per_day: float

    @field_validator("hours_per_day")
    @classmethod
    def hours_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("hours_per_day must be non-negative")
        return v


# --- Outputs ---

class VelocityProfile(BaseModel):
    """Historical average for one developer/type/domain combination."""
    developer_id: str
    ticket_type: TicketType
    domain: Domain
    avg_points_per_sprint: float
    sample_count: int  # number of sprints in the average; low = less reliable


class DeveloperCapacity(BaseModel):
    """Availability of one developer for a sprint."""
    developer_id: str
    available_days: float
    availability_ratio: float  # 0.0–1.0; multiply by baseline velocity to get budget


class AdjustedBudget(BaseModel):
    """Point budget for one developer after applying availability."""
    developer_id: str
    baseline_velocity: float
    availability_ratio: float
    adjusted_points: float


class ConfidenceInterval(BaseModel):
    """Probability range for team point delivery."""
    lower_bound: float
    upper_bound: float
    confidence_level: float  # e.g. 0.90 for 90%
    team_total_adjusted: float  # sum of adjusted_points in the current sprint
