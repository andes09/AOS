"""
Seed 6 completed sprints with realistic velocity data.

Usage:
  railway run python seed_sprints.py
"""
import os
import uuid
from datetime import date, timedelta
import psycopg2

db_url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL", "")
if not db_url:
    raise SystemExit("DATABASE_URL_SYNC or DATABASE_URL env var not set. Run via: railway run python seed_sprints.py")

# asyncpg URL → psycopg2 URL
db_url = db_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Get first team
cur.execute("SELECT id, name FROM teams LIMIT 1")
row = cur.fetchone()
if not row:
    raise SystemExit("No teams found. Create a team via the app first.")

team_id, team_name = row
print(f"Seeding sprints for team: {team_name} ({team_id})")

velocities = [32.0, 28.0, 35.0, 30.0, 38.0, 33.0]
today = date.today()

for i, velocity in enumerate(velocities):
    end = today - timedelta(weeks=2 * (i + 1))
    start = end - timedelta(days=13)
    sprint_num = len(velocities) - i
    name = f"Sprint {sprint_num} (seed)"

    cur.execute("SELECT id FROM sprints WHERE team_id = %s AND start_date = %s", (team_id, start))
    if cur.fetchone():
        print(f"  Sprint {sprint_num} already exists — skipping")
        continue

    cur.execute("""
        INSERT INTO sprints (id, team_id, name, status, start_date, end_date, committed_points, delivered_points)
        VALUES (%s, %s, %s, 'COMPLETED', %s, %s, %s, %s)
    """, (str(uuid.uuid4()), str(team_id), name, start, end, velocity + 2, velocity))
    print(f"  Created {name}: {start} → {end}, {velocity} pts delivered")

conn.commit()
cur.close()
conn.close()
print("Done.")
