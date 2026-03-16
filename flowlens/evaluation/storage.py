"""Storage layer for datasets and evaluation results."""

from __future__ import annotations

import sqlite3
from typing import Any


class DatasetStorage:
    """Manage evaluation datasets."""

    def __init__(self, db_path: str = "./eval_datasets.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_traces (
                    dataset_id TEXT,
                    trace_id TEXT,
                    trace_data TEXT,
                    PRIMARY KEY (dataset_id, trace_id),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id)
                )
                """
            )
            conn.commit()

    def create_dataset(self, name: str, description: str = "") -> str:
        """Create a new dataset."""
        import uuid

        dataset_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO datasets (id, name, description) VALUES (?, ?, ?)",
                (dataset_id, name, description),
            )
            conn.commit()
        return dataset_id

    def add_trace_to_dataset(
        self, dataset_id: str, trace_id: str, trace_data: dict[str, Any]
    ) -> None:
        """Add a trace to a dataset."""
        import json

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dataset_traces (dataset_id, trace_id, trace_data) VALUES (?, ?, ?)",
                (dataset_id, trace_id, json.dumps(trace_data)),
            )
            conn.commit()

    def get_dataset_traces(self, dataset_id: str) -> list[dict[str, Any]]:
        """Get all traces in a dataset."""
        import json

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT trace_data FROM dataset_traces WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_datasets(self) -> list[dict[str, Any]]:
        """List all datasets."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id, name, description FROM datasets").fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]


class EvaluationStorage:
    """Manage evaluation results."""

    def __init__(self, db_path: str = "./eval_results.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    evaluator_name TEXT,
                    passed INTEGER,
                    score REAL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trace_id ON evaluations(trace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_evaluator_name ON evaluations(evaluator_name)"
            )
            conn.commit()

    def save_evaluation(
        self, trace_id: str, eval_result: dict[str, Any]
    ) -> str:
        """Save an evaluation result."""
        import uuid

        result_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO evaluations
                (id, trace_id, evaluator_name, passed, score, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    trace_id,
                    eval_result.get("evaluator_name"),
                    1 if eval_result.get("passed") else 0,
                    eval_result.get("score", 0.0),
                    eval_result.get("details", ""),
                ),
            )
            conn.commit()
        return result_id

    def get_evaluations_for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        """Get all evaluations for a trace."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, trace_id, evaluator_name, passed, score, details
                FROM evaluations WHERE trace_id = ?
                """,
                (trace_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "trace_id": r[1],
                "evaluator_name": r[2],
                "passed": bool(r[3]),
                "score": r[4],
                "details": r[5],
            }
            for r in rows
        ]

    def list_evaluations(
        self, evaluator_name: str | None = None
    ) -> list[dict[str, Any]]:
        """List all evaluations, optionally filtered by evaluator."""
        with sqlite3.connect(self.db_path) as conn:
            if evaluator_name:
                rows = conn.execute(
                    """
                    SELECT id, trace_id, evaluator_name, passed, score, details
                    FROM evaluations WHERE evaluator_name = ?
                    """,
                    (evaluator_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, trace_id, evaluator_name, passed, score, details
                    FROM evaluations
                    """
                ).fetchall()

        return [
            {
                "id": r[0],
                "trace_id": r[1],
                "evaluator_name": r[2],
                "passed": bool(r[3]),
                "score": r[4],
                "details": r[5],
            }
            for r in rows
        ]
