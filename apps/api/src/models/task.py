import enum
import uuid
from datetime import date, datetime, time
from sqlalchemy import String, Text, Date, DateTime, Time, ForeignKey, Integer, Index, Boolean, false
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.database import Base


class TaskStatus(enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_milestone_id_sort_order", "milestone_id", "sort_order"),
        # The planner's dominant query: one day's tasks, chronologically.
        Index("ix_tasks_scheduled_date_time", "scheduled_date", "scheduled_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("milestones.id", ondelete="CASCADE"), index=True
    )
    # Human-referenceable handle (e.g. "AOS-142") developers put in branch
    # names / commit messages / PR titles so GitHub activity can auto-complete
    # this task. Practically unique per org — guaranteed by the atomically-
    # incremented Organization.next_task_seq counter it's derived from (see
    # src/services/task_ids.py), NOT by a DB-level constraint here: Task has
    # no denormalized organization_id column to scope a unique index to, and
    # two different orgs' slugs can normalize to the same prefix after
    # alnum-stripping, so a *global* unique constraint would be both the
    # wrong invariant and a spurious cross-tenant collision risk. Every
    # lookup (`_find_task` in integrations/github/events.py) is scoped by
    # organization_id via the Milestone->Project->Team join, so a same-string
    # short_id in two different orgs is harmless. Nullable because existing
    # tasks are backfilled by migration 0038 rather than required at the
    # column level.
    short_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, values_callable=lambda obj: [e.value for e in obj]),
        default="todo",
        server_default="todo",
    )
    sort_order: Mapped[int] = mapped_column(Integer)
    # Calendar day this task is planned for (roadmap calendar view). Nullable so
    # tasks can exist unscheduled; the generator fills it in on creation.
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Wall-clock start time. Naive on purpose (Time, never TIMETZ): "the 9:30am
    # standup" is a fact about a clock face, not an instant, so it must read the
    # same for every teammate regardless of region.
    scheduled_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    # NULL means "no explicit duration" — the card renders compact rather than
    # claiming a default block of grid space.
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True when this task has no dependency on the task before it and can be
    # tackled alongside its siblings. Drives the planner's "PARALLEL" tag and the
    # client-derived "waits its turn" fade — set by the generator/adjuster.
    parallel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # The user's latest progress note on this task, written in the day agenda.
    # Fed to the Groq adjuster so it can re-plan upcoming work around blockers
    # and slippage the user reports here.
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who owns this task. Drives both the sidebar lane and the card color.
    # SET NULL on developer delete: losing a person must not lose their work.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("developers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    github_repo: Mapped[str | None] = mapped_column(String, nullable=True)
    github_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set when GitHub activity (a merged PR referencing this task's short_id)
    # auto-completes it, or when a user manually flips status to done. NULL
    # for a task that's never been done.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    milestone: Mapped["Milestone"] = relationship(back_populates="tasks")
