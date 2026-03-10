# apps/api/tests/services/velocity/test_profiler.py
import pytest
from src.services.velocity.profiler import VelocityProfiler
from src.services.velocity.schemas import TicketRecord, TicketType, Domain


def ticket(dev, ttype, domain, points, sprint):
    return TicketRecord(
        developer_id=dev,
        ticket_type=ttype,
        domain=domain,
        story_points=points,
        sprint_id=sprint,
    )


def test_single_developer_averages_across_sprints():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 3.0, "s2"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    p = profiles[0]
    assert p.developer_id == "alice"
    assert p.avg_points_per_sprint == 4.0
    assert p.sample_count == 2


def test_multiple_tickets_same_sprint_sum_before_average():
    """Two tickets in the same sprint should be summed, not averaged."""
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 3.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),  # same sprint
        ticket("alice", TicketType.STORY, Domain.BACKEND, 4.0, "s2"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    # sprint s1 = 8pts, sprint s2 = 4pts → average = 6.0
    assert profiles[0].avg_points_per_sprint == 6.0
    assert profiles[0].sample_count == 2


def test_multi_domain_produces_separate_profiles():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.FRONTEND, 3.0, "s1"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 2
    domains = {p.domain for p in profiles}
    assert Domain.BACKEND in domains
    assert Domain.FRONTEND in domains


def test_multi_developer_independent_profiles():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("bob", TicketType.BUG, Domain.INFRA, 2.0, "s1"),
    ]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 2
    devs = {p.developer_id for p in profiles}
    assert "alice" in devs and "bob" in devs


def test_empty_tickets_returns_empty():
    profiler = VelocityProfiler()
    assert profiler.profile([]) == []


def test_overall_velocity_new_developer_returns_zero():
    profiler = VelocityProfiler()
    assert profiler.overall_velocity("nobody", []) == 0.0


def test_overall_velocity_fallback_averages_all_types():
    profiler = VelocityProfiler()
    tickets = [
        ticket("alice", TicketType.STORY, Domain.BACKEND, 5.0, "s1"),
        ticket("alice", TicketType.BUG, Domain.FRONTEND, 3.0, "s1"),
        ticket("alice", TicketType.STORY, Domain.BACKEND, 4.0, "s2"),
    ]
    # sprint s1 = 8pts, sprint s2 = 4pts → overall avg = 6.0
    assert profiler.overall_velocity("alice", tickets) == 6.0


def test_single_sprint_profile_has_low_sample_count():
    """One sprint of history returns a profile — low sample_count signals thin data."""
    profiler = VelocityProfiler()
    tickets = [ticket("alice", TicketType.STORY, Domain.BACKEND, 8.0, "s1")]
    profiles = profiler.profile(tickets)
    assert len(profiles) == 1
    assert profiles[0].sample_count == 1
    assert profiles[0].avg_points_per_sprint == 8.0
