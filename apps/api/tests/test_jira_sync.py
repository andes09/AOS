import pytest
import uuid
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
import src.models  # noqa: F401 — register all models

TEST_DB_URL = "sqlite:///./test_sync.db"


def _make_sync_session():
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _cleanup(engine):
    Base.metadata.drop_all(engine)
    engine.dispose()
    import os
    try:
        os.remove("./test_sync.db")
    except FileNotFoundError:
        pass


def test_sync_all_teams_dispatches_per_team():
    """sync_all_teams dispatches sync_jira_team.delay for each team with a board configured."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.integrations.jira.sync import sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        team_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s1", name="S1", slug="s1", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="T1", sprint_length_days=14, jira_board_id="10")
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c1",
            jira_cloud_url="https://s1.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        db.add_all([org, team, conn])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
                mock_task.delay = MagicMock()
                sync_all_teams()
                mock_task.delay.assert_called_once_with(str(team_id))
    finally:
        db.close()
        _cleanup(engine)


def test_sync_all_teams_skips_teams_without_board():
    """sync_all_teams does not dispatch for teams with no board configured."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.integrations.jira.sync import sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s2", name="S2", slug="s2", use_managed_key=False)
        team = Team(id=uuid.uuid4(), organization_id=org_id, name="T2", sprint_length_days=14)  # no board
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c2",
            jira_cloud_url="https://s2.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        db.add_all([org, team, conn])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_team") as mock_task:
                mock_task.delay = MagicMock()
                sync_all_teams()
                mock_task.delay.assert_not_called()
    finally:
        db.close()
        _cleanup(engine)


def test_incremental_sync_all_teams_dispatches_active_sprint():
    """incremental_sync_all_teams dispatches sync_jira_sprint.delay for each team with an active sprint."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.models.sprint import Sprint, SprintStatus
    from src.integrations.jira.sync import incremental_sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        team_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s3", name="S3", slug="s3", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="T3", sprint_length_days=14, jira_board_id="10")
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c3",
            jira_cloud_url="https://s3.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        sprint = Sprint(
            id=uuid.uuid4(),
            team_id=team_id,
            name="Sprint 1",
            status=SprintStatus.ACTIVE,
            jira_sprint_id="sprint_1",
        )
        db.add_all([org, team, conn, sprint])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_sprint") as mock_task:
                mock_task.delay = MagicMock()
                incremental_sync_all_teams()
                mock_task.delay.assert_called_once_with(str(team_id), "sprint_1")
    finally:
        db.close()
        _cleanup(engine)


def test_incremental_sync_all_teams_no_dispatch_without_active_sprint():
    """incremental_sync_all_teams does not dispatch when there is no active sprint."""
    from src.models.organization import Organization
    from src.models.team import Team
    from src.models.jira_connection import JiraConnection
    from src.models.sprint import Sprint, SprintStatus
    from src.integrations.jira.sync import incremental_sync_all_teams

    db, engine = _make_sync_session()
    try:
        org_id = uuid.uuid4()
        team_id = uuid.uuid4()
        org = Organization(id=org_id, clerk_org_id="org_s4", name="S4", slug="s4", use_managed_key=False)
        team = Team(id=team_id, organization_id=org_id, name="T4", sprint_length_days=14, jira_board_id="10")
        conn = JiraConnection(
            id=uuid.uuid4(),
            organization_id=org_id,
            jira_cloud_id="c4",
            jira_cloud_url="https://s4.atlassian.net",
            encrypted_access_token="x",
            encrypted_refresh_token="x",
            is_active=True,
        )
        sprint = Sprint(
            id=uuid.uuid4(),
            team_id=team_id,
            name="Sprint 0",
            status=SprintStatus.COMPLETED,
            jira_sprint_id="sprint_0",
        )
        db.add_all([org, team, conn, sprint])
        db.commit()

        with patch("src.integrations.jira.sync._get_sync_session", return_value=db):
            with patch("src.integrations.jira.sync.sync_jira_sprint") as mock_task:
                mock_task.delay = MagicMock()
                incremental_sync_all_teams()
                mock_task.delay.assert_not_called()
    finally:
        db.close()
        _cleanup(engine)
