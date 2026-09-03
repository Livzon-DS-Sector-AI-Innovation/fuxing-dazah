"""S0 ticket 02 验收：5 张 Agent 辅助表已建齐（live，直查 whdev 库结构）。"""

import os

import asyncpg
import pytest

DSN = os.environ.get(
    "WAREHOUSE_LIVE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/dazah_whdev",
)

EXPECTED_TABLES = {
    "warehouse_agent_drafts",
    "warehouse_agent_sessions",
    "warehouse_agent_audit",
    "warehouse_agent_plans",
    "warehouse_agent_memories",
}


@pytest.fixture
async def conn():
    c = await asyncpg.connect(DSN)
    yield c
    await c.close()


async def test_five_agent_tables_exist(conn):
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='warehouse' AND tablename = ANY($1)",
        sorted(EXPECTED_TABLES),
    )
    assert {r["tablename"] for r in rows} == EXPECTED_TABLES


async def test_unique_indexes_present(conn):
    rows = await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname='warehouse' AND indexname = ANY($1)",
        [
            "uq_warehouse_agent_drafts_no",
            "uq_warehouse_agent_plans_no",
            "uq_warehouse_agent_sessions_key",
        ],
    )
    assert len(rows) == 3


async def test_key_columns_present(conn):
    cols = await conn.fetch(
        """SELECT table_name, column_name, data_type FROM information_schema.columns
           WHERE table_schema='warehouse'
             AND (table_name, column_name) IN (
                 ('warehouse_agent_drafts','recognized'), ('warehouse_agent_drafts','aligned'),
                 ('warehouse_agent_drafts','expires_at'), ('warehouse_agent_sessions','history'),
                 ('warehouse_agent_audit','args_summary'), ('warehouse_agent_plans','steps'),
                 ('warehouse_agent_memories','memory_type'))"""
    )
    by_key = {(r["table_name"], r["column_name"]): r["data_type"] for r in cols}
    assert by_key[("warehouse_agent_drafts", "recognized")] == "jsonb"
    assert by_key[("warehouse_agent_drafts", "aligned")] == "jsonb"
    assert by_key[("warehouse_agent_sessions", "history")] == "jsonb"
    assert by_key[("warehouse_agent_audit", "args_summary")] == "jsonb"
    assert by_key[("warehouse_agent_plans", "steps")] == "jsonb"
    assert by_key[("warehouse_agent_drafts", "expires_at")] == "timestamp with time zone"
    assert by_key[("warehouse_agent_memories", "memory_type")] == "character varying"
