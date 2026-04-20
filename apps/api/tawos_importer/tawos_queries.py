"""Read-only queries against the TAWOS MySQL.

Kept separate from importer.py so the SQL is easy to review and tweak as we
discover quirks in the dataset. All functions take a PyMySQL connection with a
DictCursor and return lists of dicts.

All table/column names here reflect the TAWOS v1.1 schema. If your dump uses
different casing, edit this file — it's the single source of truth for SQL.
"""
from __future__ import annotations

from typing import Any


def list_projects(conn) -> list[dict[str, Any]]:
    """Every TAWOS project with its issue count, ordered by size descending."""
    sql = """
        SELECT p.ID, p.Name, p.`Key`,
               (SELECT COUNT(*) FROM Issue i WHERE i.Project_ID = p.ID) AS issue_count
        FROM Project p
        ORDER BY issue_count DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_project(conn, project_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM Project WHERE ID = %s", (project_id,))
        return cur.fetchone()


def fetch_project_by_key(conn, key: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM Project WHERE `Key` = %s", (key,))
        return cur.fetchone()


def fetch_users_for_project(conn, project_id: int) -> list[dict[str, Any]]:
    """Every TAWOS user who touched an issue in this project — assignee OR reporter.

    We include reporters so tickets with no assignee still have a recognisable
    identity behind them; spec calls this out as an edge case to handle.
    """
    sql = """
        SELECT DISTINCT u.*
        FROM User u
        WHERE u.ID IN (
            SELECT Assignee_ID FROM Issue WHERE Project_ID = %s AND Assignee_ID IS NOT NULL
            UNION
            SELECT Reporter_ID FROM Issue WHERE Project_ID = %s AND Reporter_ID IS NOT NULL
        )
    """
    with conn.cursor() as cur:
        cur.execute(sql, (project_id, project_id))
        return cur.fetchall()


def fetch_sprints(conn, project_id: int) -> list[dict[str, Any]]:
    """Sprints for a project, ordered oldest first so sprint_lookup gets
    deterministic IDs when we need to re-run."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM Sprint WHERE Project_ID = %s ORDER BY COALESCE(Start_Date, '1970-01-01') ASC",
            (project_id,),
        )
        return cur.fetchall()


def fetch_issues(conn, project_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    """Every issue in the project. `limit` is applied at the SQL level so we
    don't fetch millions of rows only to discard them."""
    sql = "SELECT * FROM Issue WHERE Project_ID = %s ORDER BY ID ASC"
    params: tuple = (project_id,)
    if limit is not None:
        sql += " LIMIT %s"
        params = (project_id, int(limit))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_blocking_links(conn, issue_ids: list[int]) -> list[dict[str, Any]]:
    """Issue_Link rows of type 'blocks'/'is blocked by' for the given issues.

    Includes the link type name and both endpoint keys so the mapper doesn't
    need another round-trip for classification.
    """
    if not issue_ids:
        return []
    placeholders = ",".join(["%s"] * len(issue_ids))
    sql = f"""
        SELECT il.ID, il.Source_Issue_ID, il.Target_Issue_ID,
               lt.Name AS Link_Type_Name,
               si.`Key` AS Source_Key, ti.`Key` AS Target_Key,
               si.Title AS Source_Title, ti.Title AS Target_Title,
               si.Resolution_Date AS Source_Resolved,
               ti.Sprint_ID AS Target_Sprint_ID,
               si.Sprint_ID AS Source_Sprint_ID
        FROM Issue_Link il
        JOIN Link_Type lt ON lt.ID = il.Link_Type_ID
        JOIN Issue si ON si.ID = il.Source_Issue_ID
        JOIN Issue ti ON ti.ID = il.Target_Issue_ID
        WHERE (il.Source_Issue_ID IN ({placeholders}) OR il.Target_Issue_ID IN ({placeholders}))
          AND (LOWER(lt.Name) LIKE '%block%' OR LOWER(lt.Outward_Description) LIKE '%block%')
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(issue_ids) + tuple(issue_ids))
        return cur.fetchall()


def fetch_issue_sprint_history(conn, issue_ids: list[int]) -> dict[int, list[int]]:
    """issue_id → list of sprint_ids the issue was ever associated with.

    TAWOS may have this in a Sprint_Issue join table or in Issue_Changelog.
    We try the join table first; if it doesn't exist, return {} and the
    importer falls back to single-sprint assignment (is_carryover always False).
    """
    if not issue_ids:
        return {}
    placeholders = ",".join(["%s"] * len(issue_ids))

    # Try the common mapping table names. TAWOS v1.1 has `Sprint_Issue`.
    candidates = (
        ("Sprint_Issue", "Sprint_ID", "Issue_ID"),
    )
    for table, sprint_col, issue_col in candidates:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {issue_col} AS issue_id, {sprint_col} AS sprint_id "
                    f"FROM `{table}` WHERE {issue_col} IN ({placeholders})",
                    tuple(issue_ids),
                )
                rows = cur.fetchall()
        except Exception:
            continue
        out: dict[int, list[int]] = {}
        for row in rows:
            out.setdefault(int(row["issue_id"]), []).append(int(row["sprint_id"]))
        return out
    return {}
