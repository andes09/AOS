"""TAWOS dataset importer.

Loads real Jira data from the TAWOS dataset (https://github.com/SOLAR-group/TAWOS)
into Omada's Postgres schema so every feature can be exercised against realistic
data volume and shapes.

Note: TAWOS ships as a MySQL 8.0 dump, not SQLite. This importer uses a local
MySQL (see docker-compose.yml in this directory) as the source, and writes to
Omada's Postgres via SQLAlchemy.
"""
