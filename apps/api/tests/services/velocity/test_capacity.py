# apps/api/tests/services/velocity/test_capacity.py
import pytest
from src.services.velocity.capacity import CapacityModel
from src.services.velocity.schemas import SprintMeta, PtoEntry, MeetingOverhead


def sprint(days, members):
    return SprintMeta(total_working_days=days, team_members=members)


def test_full_availability_no_deductions():
    model = CapacityModel()
    result = model.model(sprint(10, ["alice"]), [], [])
    assert len(result) == 1
    assert result[0].developer_id == "alice"
    assert result[0].availability_ratio == 1.0
    assert result[0].available_days == 10.0


def test_full_pto_gives_zero_availability():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=10.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].availability_ratio == 0.0
    assert result[0].available_days == 0.0


def test_pto_exceeding_sprint_clamped_to_zero():
    """Days off > sprint length should not produce negative availability."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=15.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].available_days == 0.0
    assert result[0].availability_ratio == 0.0


def test_partial_pto():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=2.0)]
    result = model.model(sprint(10, ["alice"]), pto, [])
    assert result[0].available_days == 8.0
    assert result[0].availability_ratio == pytest.approx(0.8)


def test_meeting_overhead_deducts_equivalent_days():
    """2 hours/day meetings over 10-day sprint = 2.5 days lost (2*10/8)."""
    model = CapacityModel()
    meetings = [MeetingOverhead(developer_id="alice", hours_per_day=2.0)]
    result = model.model(sprint(10, ["alice"]), [], meetings)
    assert result[0].available_days == 7.5
    assert result[0].availability_ratio == pytest.approx(0.75)


def test_pto_and_meetings_combined():
    """2 days PTO + 2 hrs/day meetings (2.5 days) = 5.5 days available."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=2.0)]
    meetings = [MeetingOverhead(developer_id="alice", hours_per_day=2.0)]
    result = model.model(sprint(10, ["alice"]), pto, meetings)
    assert result[0].available_days == 5.5
    assert result[0].availability_ratio == pytest.approx(0.55)


def test_developer_without_pto_entry_gets_full_days():
    """If a team member has no PTO entry, they lose no days."""
    model = CapacityModel()
    pto = [PtoEntry(developer_id="bob", days_off=3.0)]
    result = model.model(sprint(10, ["alice", "bob"]), pto, [])
    alice = next(r for r in result if r.developer_id == "alice")
    assert alice.available_days == 10.0


def test_multiple_team_members_independent():
    model = CapacityModel()
    pto = [PtoEntry(developer_id="alice", days_off=5.0)]
    result = model.model(sprint(10, ["alice", "bob"]), pto, [])
    alice = next(r for r in result if r.developer_id == "alice")
    bob = next(r for r in result if r.developer_id == "bob")
    assert alice.availability_ratio == pytest.approx(0.5)
    assert bob.availability_ratio == pytest.approx(1.0)
