"""
Verification script for Track 22 enrichment.
Run from apps/api/: python verify_enrichment.py
"""
import asyncio
import sys
import psycopg2
import psycopg2.extras
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ASYNC_DB = "postgresql+asyncpg://agileos:agileos_dev@localhost:5432/agileos"
SYNC_DB = "postgresql://agileos:agileos_dev@localhost:5432/agileos"

TEAM_ID = "993572c5-18a3-43c3-8903-adfbbf518d45"
TICKET_KEY = "AOS-101"

# NullPool forces a brand-new connection for every test call — no stale pool state
engine = create_async_engine(ASYNC_DB, echo=False, poolclass=NullPool)
AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def sync_exec(sql, params=None):
    conn = psycopg2.connect(SYNC_DB)
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    cur.close()
    conn.close()


def sync_query(sql, params=None):
    conn = psycopg2.connect(SYNC_DB)
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def insert_scope_row(status_val):
    sync_exec(
        "DELETE FROM ticket_analyses WHERE team_id=%s AND ticket_key=%s",
        (TEAM_ID, TICKET_KEY),
    )
    sync_exec(
        """INSERT INTO ticket_analyses (team_id, ticket_key, status, issues)
           VALUES (%s, %s, %s, %s::jsonb)""",
        (TEAM_ID, TICKET_KEY, status_val, '["Missing acceptance criteria","No story points"]'),
    )
    row = sync_query(
        "SELECT status FROM ticket_analyses WHERE team_id=%s AND ticket_key=%s",
        (TEAM_ID, TICKET_KEY),
    )
    print(f"  [db check] status in DB = {row[0]!r}")


def delete_scope_row():
    sync_exec(
        "DELETE FROM ticket_analyses WHERE team_id=%s AND ticket_key=%s",
        (TEAM_ID, TICKET_KEY),
    )


def insert_dep_row(ticket_key=TICKET_KEY):
    sync_exec(
        """INSERT INTO dependencies (team_id, ticket_key, dependency_type, risk_level, description)
           VALUES (%s, %s, 'blocks', 'high', 'Blocked by infrastructure work')""",
        (TEAM_ID, ticket_key),
    )


def delete_dep_rows():
    sync_exec("DELETE FROM dependencies WHERE team_id=%s", (TEAM_ID,))


async def run_enrichment(assigned_keys):
    from src.routers.sprint_brain import _build_enrichment
    async with AsyncSessionFactory() as db:
        result = await _build_enrichment(TEAM_ID, assigned_keys, db)
        return result


async def main():
    assigned = [TICKET_KEY]
    errors = []

    print("=" * 60)
    print("Track 22 Enrichment Verification")
    print("=" * 60)

    # --- TEST 1: Empty tables → not_analyzed + not_scanned ---
    print("\n[1] Empty tables → not_analyzed + not_scanned")
    delete_scope_row()
    delete_dep_rows()
    sw, dw, es, hw, _ = await run_enrichment(assigned)
    ok1a = es.scope_cop == "not_analyzed"
    ok1b = es.dependency_radar == "not_scanned"
    print(f"  scopeCop={es.scope_cop!r}  {'✓' if ok1a else '✗ EXPECTED not_analyzed'}")
    print(f"  dependencyRadar={es.dependency_radar!r}  {'✓' if ok1b else '✗ EXPECTED not_scanned'}")
    if not ok1a:
        errors.append("Empty table: scopeCop should be not_analyzed")
    if not ok1b:
        errors.append("Empty table: dependencyRadar should be not_scanned")

    # --- TEST 2: Scope row with status='needs_work' → has_issues ---
    print("\n[2] ticket_analysis status='needs_work' → has_issues")
    insert_scope_row("needs_work")
    sw, dw, es, hw, _ = await run_enrichment(assigned)
    ok2a = es.scope_cop == "has_issues"
    ok2b = len(sw) > 0
    print(f"  scopeCop={es.scope_cop!r}  {'✓' if ok2a else '✗ EXPECTED has_issues'}")
    print(f"  scopeWarnings count={len(sw)}  {'✓' if ok2b else '✗ EXPECTED non-empty'}")
    if sw:
        print(f"  first warning: ticketId={sw[0].ticket_id!r} status={sw[0].status!r} issues={sw[0].issues}")
    if not ok2a:
        errors.append(f"has_issues test: scopeCop={es.scope_cop!r}, expected has_issues")
    if not ok2b:
        errors.append("has_issues test: scopeWarnings is empty")

    # --- TEST 3: Scope row with status='ready' → all_ready ---
    print("\n[3] ticket_analysis status='ready' → all_ready")
    insert_scope_row("ready")
    sw, dw, es, hw, _ = await run_enrichment(assigned)
    ok3 = es.scope_cop == "all_ready" and len(sw) == 0
    print(f"  scopeCop={es.scope_cop!r} scopeWarnings={len(sw)}  {'✓' if ok3 else '✗ EXPECTED all_ready + empty warnings'}")
    if not ok3:
        errors.append(f"all_ready test: scopeCop={es.scope_cop!r} warnings={len(sw)}")

    delete_scope_row()

    # --- TEST 4: High-risk dep on assigned ticket → has_risks ---
    print("\n[4] dependency risk_level='high' on assigned ticket → has_risks")
    insert_dep_row(TICKET_KEY)
    sw, dw, es, hw, _ = await run_enrichment(assigned)
    ok4a = es.dependency_radar == "has_risks"
    ok4b = len(dw) > 0
    print(f"  dependencyRadar={es.dependency_radar!r}  {'✓' if ok4a else '✗ EXPECTED has_risks'}")
    print(f"  depWarnings count={len(dw)}  {'✓' if ok4b else '✗ EXPECTED non-empty'}")
    if dw:
        print(f"  first warning: ticketId={dw[0].ticket_id!r} riskLevel={dw[0].risk_level!r}")
    if not ok4a:
        errors.append(f"has_risks test: dependencyRadar={es.dependency_radar!r}")
    if not ok4b:
        errors.append("has_risks test: depWarnings is empty")

    # --- TEST 5: Dep data exists but not for assigned ticket → no_risks ---
    print("\n[5] dep data exists but NOT for assigned ticket → no_risks")
    delete_dep_rows()
    insert_dep_row("AOS-999")  # different ticket
    sw, dw, es, hw, _ = await run_enrichment(assigned)
    ok5 = es.dependency_radar == "no_risks"
    print(f"  dependencyRadar={es.dependency_radar!r}  {'✓' if ok5 else '✗ EXPECTED no_risks'}")
    if not ok5:
        errors.append(f"no_risks test: dependencyRadar={es.dependency_radar!r}")

    delete_dep_rows()

    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED — {len(errors)} error(s):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
