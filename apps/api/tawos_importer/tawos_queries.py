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
    """Every TAWOS project with its issue count, ordered by size descending.

    Returns a `Key` field (aliased from Project_Key) so downstream CLI/importer
    code doesn't care about the actual column name.
    """
    sql = """
        SELECT p.ID, p.Name, p.Project_Key AS `Key`,
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
        cur.execute("SELECT * FROM Project WHERE Project_Key = %s", (key,))
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
    """Issue_Link rows representing 'blocks'/'is blocked by' relationships.

    The TAWOS dump ships Issue_Link with columns:
        ID, Issue_ID, Target_Issue_ID, Name, Description, Direction
    There is NO separate Link_Type table — the link's human-readable text is
    in Issue_Link.Name (e.g. 'Blocks') and Issue_Link.Description (e.g. 'is
    blocked by', 'blocks'). Direction is 'INBOUND' | 'OUTBOUND' from the
    perspective of Issue_ID. Each logical link is typically stored twice
    (once per side); the mapper deduplicates.

    Literal `%` must be doubled to survive PyMySQL's param substitution.
    """
    if not issue_ids:
        return []
    placeholders = ",".join(["%s"] * len(issue_ids))
    sql = f"""
        SELECT il.ID, il.Issue_ID, il.Target_Issue_ID,
               il.Name        AS Link_Name,
               il.Description AS Link_Description,
               il.Direction   AS Link_Direction,
               i1.Issue_Key      AS Source_Key,
               i2.Issue_Key      AS Target_Key,
               i1.Title          AS Source_Title,
               i2.Title          AS Target_Title,
               i1.Resolution_Date AS Source_Resolved,
               i2.Resolution_Date AS Target_Resolved,
               i1.Sprint_ID       AS Source_Sprint_ID,
               i2.Sprint_ID       AS Target_Sprint_ID,
               i1.Creation_Date   AS Source_Created,
               i2.Creation_Date   AS Target_Created,
               i1.Status          AS Source_Status,
               i2.Status          AS Target_Status
        FROM Issue_Link il
        JOIN Issue i1 ON i1.ID = il.Issue_ID
        JOIN Issue i2 ON i2.ID = il.Target_Issue_ID
        WHERE (il.Issue_ID IN ({placeholders}) OR il.Target_Issue_ID IN ({placeholders}))
          AND (LOWER(il.Name) LIKE '%%block%%' OR LOWER(il.Description) LIKE '%%block%%')
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
