"""SQLite persistence helpers for action items and analysis snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS action_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                acceptance_criteria TEXT NOT NULL DEFAULT '[]',
                type TEXT NOT NULL CHECK(type IN ('Feature', 'Bug', 'Task'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(analysis_runs)").fetchall()]
        if "effective_result_json" not in columns:
            conn.execute("ALTER TABLE analysis_runs ADD COLUMN effective_result_json TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_run_id INTEGER NOT NULL,
                feedback_text TEXT NOT NULL,
                action_item_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL CHECK(feedback_type IN ('Feature', 'Bug', 'Task')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            DELETE FROM manual_mappings
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM manual_mappings
                GROUP BY analysis_run_id, lower(feedback_text)
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS manual_mapping_unique_feedback
            ON manual_mappings(analysis_run_id, lower(feedback_text))
            """
        )


def list_action_items() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, description, acceptance_criteria, type FROM action_items ORDER BY id"
        ).fetchall()

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "acceptance_criteria": json.loads(row["acceptance_criteria"]),
            "type": row["type"],
        }
        for row in rows
    ]


def upsert_action_item(item: dict) -> None:
    payload = {
        "id": item["id"],
        "title": item["title"],
        "description": item.get("description", ""),
        "acceptance_criteria": json.dumps(item.get("acceptance_criteria", [])),
        "type": item["type"],
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO action_items (id, title, description, acceptance_criteria, type)
            VALUES (:id, :title, :description, :acceptance_criteria, :type)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                acceptance_criteria=excluded.acceptance_criteria,
                type=excluded.type
            """,
            payload,
        )


def delete_action_item(item_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM action_items WHERE id = ?", (item_id,))
    return cur.rowcount > 0


def save_analysis_run(transcript: str, result: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO analysis_runs (transcript, result_json) VALUES (?, ?)",
            (transcript, json.dumps(result)),
        )
    return int(cur.lastrowid)


def list_analysis_runs(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, transcript, result_json, effective_result_json, created_at
            FROM analysis_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result: list[dict] = []
    for row in rows:
        effective = row["effective_result_json"]
        parsed = json.loads(effective) if effective else json.loads(row["result_json"])
        transcript = row["transcript"].strip().replace("\n", " ")
        result.append(
            {
                "id": row["id"],
                "created_at": str(row["created_at"]),
                "transcript_preview": transcript[:120] + ("..." if len(transcript) > 120 else ""),
                "mapped_count": len(parsed.get("mapped_feedback", [])),
                "unmapped_count": len(parsed.get("unmapped_feedback", [])),
                "suggestion_count": len(parsed.get("suggestions", [])),
            }
        )
    return result


def get_analysis_run(run_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, transcript, result_json, effective_result_json, created_at
            FROM analysis_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": str(row["created_at"]),
        "transcript": row["transcript"],
        "result": json.loads(row["result_json"]),
        "effective_result": json.loads(row["effective_result_json"]) if row["effective_result_json"] else None,
    }


def save_manual_mapping(mapping: dict) -> dict:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO manual_mappings (analysis_run_id, feedback_text, action_item_id, feedback_type)
            VALUES (:analysis_run_id, :feedback_text, :action_item_id, :feedback_type)
            """,
            mapping,
        )
        row_id = int(cur.lastrowid)
        row = conn.execute(
            """
            SELECT id, analysis_run_id, feedback_text, action_item_id, feedback_type, created_at
            FROM manual_mappings
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()
    return dict(row) if row else {}


def get_manual_mapping(mapping_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, analysis_run_id, feedback_text, action_item_id, feedback_type, created_at
            FROM manual_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        ).fetchone()
    return dict(row) if row else None


def update_manual_mapping(mapping_id: int, mapping: dict) -> dict | None:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE manual_mappings
            SET feedback_text = :feedback_text, action_item_id = :action_item_id, feedback_type = :feedback_type
            WHERE id = :id
            """,
            {"id": mapping_id, **mapping},
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            """
            SELECT id, analysis_run_id, feedback_text, action_item_id, feedback_type, created_at
            FROM manual_mappings
            WHERE id = ?
            """,
            (mapping_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_manual_mapping(mapping_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM manual_mappings WHERE id = ?", (mapping_id,))
    return cur.rowcount > 0


def list_manual_mappings(run_id: int | None = None) -> list[dict]:
    query = """
        SELECT id, analysis_run_id, feedback_text, action_item_id, feedback_type, created_at
        FROM manual_mappings
    """
    params: tuple = ()
    if run_id is not None:
        query += " WHERE analysis_run_id = ?"
        params = (run_id,)
    query += " ORDER BY id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def set_effective_result(run_id: int, result: dict | None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE analysis_runs SET effective_result_json = ? WHERE id = ?",
            (json.dumps(result) if result is not None else None, run_id),
        )
