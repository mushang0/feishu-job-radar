from __future__ import annotations

import json
import gc
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .backup import BackupService
from .models import Job, MatchResult


class _ClosingConnection(sqlite3.Connection):
    """Close SQLite connections when a context-manager block exits."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


_SCHEMA_COLUMNS: dict[str, dict[str, str]] = {
    "jobs": {
        "source": "TEXT", "source_job_id": "TEXT", "source_url": "TEXT", "detail_url": "TEXT",
        "dedupe_key": "TEXT", "company": "TEXT", "raw_company": "TEXT", "company_normalized": "TEXT",
        "title": "TEXT", "raw_title": "TEXT", "clean_title": "TEXT", "summary": "TEXT", "batch": "TEXT",
        "target_graduate_year": "TEXT", "degree": "TEXT", "city": "TEXT", "location_text": "TEXT",
        "collected_date": "DATE", "deadline": "DATE", "company_type": "TEXT", "industry": "TEXT",
        "tags": "TEXT", "job_tags": "TEXT", "special_marks": "TEXT", "raw_tags": "TEXT", "raw_text": "TEXT",
        "role_text": "TEXT", "announcement_text": "TEXT", "role_signals": "TEXT", "field_evidence": "TEXT",
        "extraction_version": "TEXT", "apply_url": "TEXT", "official_url": "TEXT", "parse_status": "TEXT",
        "parse_note": "TEXT", "first_seen": "DATETIME", "last_seen": "DATETIME", "last_checked": "DATETIME",
        "content_hash": "TEXT", "is_active": "INTEGER",
    },
    "job_matches": {
        "job_id": "INTEGER", "matched_keywords": "TEXT", "matched_strong_keywords": "TEXT",
        "matched_weak_keywords": "TEXT", "matched_industry_keywords": "TEXT", "matched_company_rule": "TEXT",
        "matched_city_rule": "TEXT", "negative_keywords": "TEXT", "match_score": "INTEGER", "priority": "TEXT",
        "is_relevant": "INTEGER", "should_push": "INTEGER", "needs_verify": "INTEGER", "match_reason": "TEXT",
        "verify_status": "TEXT", "suggested_search_terms": "TEXT", "match_config_version": "TEXT",
        "matched_at": "DATETIME", "recommend_reason": "TEXT",
    },
    "job_user_state": {
        "job_id": "INTEGER", "status": "TEXT", "official_url": "TEXT", "apply_url_manual": "TEXT",
        "next_action": "TEXT", "note": "TEXT", "updated_at": "DATETIME",
    },
    "scan_runs": {
        "id": "INTEGER", "run_type": "TEXT", "started_at": "DATETIME", "finished_at": "DATETIME",
        "status": "TEXT", "pages_scanned": "INTEGER", "items_seen": "INTEGER", "new_items": "INTEGER",
        "updated_items": "INTEGER", "error_message": "TEXT", "notification_status": "TEXT",
    },
    "feishu_sync": {
        "job_id": "INTEGER", "feishu_record_id": "TEXT", "last_synced_at": "DATETIME", "sync_status": "TEXT",
        "sync_error": "TEXT",
    },
    "recommended_jobs": {
        "id": "INTEGER", "recommendation_date": "DATE", "job_id": "INTEGER", "recommend_reason": "TEXT",
        "created_at": "DATETIME",
    },
}
_SCHEMA_INDEXES = {"idx_recommended_jobs_job_id": "recommended_jobs"}


@dataclass(frozen=True, slots=True)
class UpsertResult:
    job_id: int
    created: bool
    changed: bool = False


class JobRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, factory=_ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_schema_in_place(self) -> None:
        with self.connect() as conn:
            self._validate_schema_objects(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY,
                    source TEXT,
                    source_job_id TEXT,
                    source_url TEXT,
                    detail_url TEXT,
                    dedupe_key TEXT UNIQUE NOT NULL,
                    company TEXT,
                    raw_company TEXT,
                    company_normalized TEXT,
                    title TEXT,
                    raw_title TEXT,
                    clean_title TEXT,
                    summary TEXT,
                    batch TEXT,
                    target_graduate_year TEXT,
                    degree TEXT,
                    city TEXT,
                    location_text TEXT,
                    collected_date DATE,
                    deadline DATE,
                    company_type TEXT,
                    industry TEXT,
                    tags TEXT,
                    job_tags TEXT,
                    special_marks TEXT,
                    raw_tags TEXT,
                    raw_text TEXT,
                    role_text TEXT,
                    announcement_text TEXT,
                    role_signals TEXT,
                    field_evidence TEXT,
                    extraction_version TEXT,
                    apply_url TEXT,
                    official_url TEXT,
                    parse_status TEXT,
                    parse_note TEXT,
                    first_seen DATETIME,
                    last_seen DATETIME,
                    last_checked DATETIME,
                    content_hash TEXT,
                    is_active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS job_matches (
                    job_id INTEGER UNIQUE,
                    matched_keywords TEXT,
                    matched_strong_keywords TEXT,
                    matched_weak_keywords TEXT,
                    matched_industry_keywords TEXT,
                    matched_company_rule TEXT,
                    matched_city_rule TEXT,
                    negative_keywords TEXT,
                    match_score INTEGER,
                    priority TEXT,
                    is_relevant INTEGER,
                    should_push INTEGER,
                    needs_verify INTEGER,
                    match_reason TEXT,
                    verify_status TEXT,
                    suggested_search_terms TEXT,
                    match_config_version TEXT,
                    matched_at DATETIME,
                    recommend_reason TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS job_user_state (
                    job_id INTEGER UNIQUE,
                    status TEXT DEFAULT '未看',
                    official_url TEXT,
                    apply_url_manual TEXT,
                    next_action TEXT,
                    note TEXT,
                    updated_at DATETIME,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id INTEGER PRIMARY KEY,
                    run_type TEXT,
                    started_at DATETIME,
                    finished_at DATETIME,
                    status TEXT,
                    pages_scanned INTEGER,
                    items_seen INTEGER,
                    new_items INTEGER,
                    updated_items INTEGER,
                    error_message TEXT,
                    notification_status TEXT
                );
                CREATE TABLE IF NOT EXISTS feishu_sync (
                    job_id INTEGER UNIQUE,
                    feishu_record_id TEXT,
                    last_synced_at DATETIME,
                    sync_status TEXT,
                    sync_error TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS recommended_jobs (
                    id INTEGER PRIMARY KEY,
                    recommendation_date DATE NOT NULL,
                    job_id INTEGER NOT NULL,
                    recommend_reason TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE(recommendation_date, job_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_recommended_jobs_job_id ON recommended_jobs(job_id);
                """
            )
            self._ensure_columns(conn, "jobs", {
                "raw_title": "TEXT",
                "raw_company": "TEXT",
                "clean_title": "TEXT",
                "summary": "TEXT",
                "location_text": "TEXT",
                "official_url": "TEXT",
                "job_tags": "TEXT",
                "special_marks": "TEXT",
                "raw_tags": "TEXT",
                "parse_status": "TEXT",
                "parse_note": "TEXT",
                "role_text": "TEXT",
                "announcement_text": "TEXT",
                "role_signals": "TEXT",
                "field_evidence": "TEXT",
                "extraction_version": "TEXT",
            })
            self._ensure_columns(conn, "job_matches", {
                "matched_strong_keywords": "TEXT",
                "matched_weak_keywords": "TEXT",
                "matched_industry_keywords": "TEXT",
                "should_push": "INTEGER",
                "needs_verify": "INTEGER",
                "match_config_version": "TEXT",
                "recommend_reason": "TEXT",
            })
            self._ensure_columns(conn, "job_user_state", {
                "apply_url_manual": "TEXT",
                "next_action": "TEXT",
            })
            self._ensure_columns(conn, "scan_runs", {
                "notification_status": "TEXT",
            })
            for table, columns in _SCHEMA_COLUMNS.items():
                self._ensure_columns(conn, table, columns)

    def init_schema(self) -> None:
        if not self.db_path.exists():
            self._apply_schema_in_place()
            return
        if not self._schema_needs_upgrade():
            return

        BackupService(self.db_path.parent / "backups").backup_sqlite(self.db_path, source="schema-upgrade")
        file_handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.db_path.name}.", suffix=".migration.tmp", dir=self.db_path.parent
        )
        os.close(file_handle)
        temporary_path = Path(temporary_name)
        try:
            self._copy_database(temporary_path)
            migrated = JobRepository(temporary_path)
            migrated._apply_schema_in_place()
            if migrated._schema_needs_upgrade():
                raise sqlite3.DatabaseError("schema migration did not produce the required schema")
            # Release every connection/cursor owned by the temporary repository
            # before replacing the database on Windows.
            del migrated
            gc.collect()
            os.replace(temporary_path, self.db_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _schema_needs_upgrade(self) -> bool:
        if not self.db_path.exists():
            return False
        conn = self.connect()
        try:
            objects = {
                row["name"]: row["type"]
                for row in conn.execute("SELECT name, type FROM sqlite_master")
            }
            for table, columns in _SCHEMA_COLUMNS.items():
                if objects.get(table) != "table":
                    return True
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not set(columns).issubset(existing):
                    return True
            for index_name in _SCHEMA_INDEXES:
                if objects.get(index_name) != "index":
                    return True
            return False
        finally:
            conn.close()

    def _validate_schema_objects(self, conn: sqlite3.Connection) -> None:
        objects = {
            row["name"]: row["type"]
            for row in conn.execute("SELECT name, type FROM sqlite_master")
        }
        for table in _SCHEMA_COLUMNS:
            if table in objects and objects[table] != "table":
                raise sqlite3.DatabaseError(f"schema object {table!r} is not a table")
        for index_name in _SCHEMA_INDEXES:
            if index_name in objects and objects[index_name] != "index":
                raise sqlite3.DatabaseError(f"schema object {index_name!r} is not an index")

    def _copy_database(self, target_path: Path) -> None:
        source = sqlite3.connect(self.db_path)
        target = sqlite3.connect(target_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def _schema_backup_needed(self) -> bool:
        """Compatibility alias for callers that used the old migration probe."""
        return self._schema_needs_upgrade()

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, sql_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    def upsert_job(self, job: Job) -> UpsertResult:
        values = job.as_db_values()
        if not values["dedupe_key"]:
            raise ValueError("job.dedupe_key is required before storing")
        columns = list(values)
        placeholders = ", ".join(f":{column}" for column in columns)
        update_columns = [column for column in columns if column not in {"dedupe_key", "first_seen", "official_url"}]
        update_assignments = [f"{column}=excluded.{column}" for column in update_columns]
        update_assignments.append(
            "official_url=CASE "
            "WHEN jobs.official_url IS NULL OR jobs.official_url = '' THEN excluded.official_url "
            "ELSE jobs.official_url END"
        )
        update_clause = ", ".join(update_assignments)
        with self.connect() as conn:
            before = conn.execute("SELECT * FROM jobs WHERE dedupe_key = ?", (values["dedupe_key"],)).fetchone()
            if before and before["parse_status"] == "detail_ready" and values.get("parse_status") != "detail_ready":
                # A failed retry only carries list-page data.  Never let it erase a
                # previously parsed detail record.
                protected = {
                    "company", "company_normalized", "title", "raw_title", "clean_title", "summary",
                    "batch", "target_graduate_year", "degree", "city", "location_text", "deadline",
                    "job_tags", "raw_text", "role_text", "announcement_text", "role_signals",
                    "field_evidence", "extraction_version", "apply_url", "parse_status", "parse_note",
                    "content_hash",
                }
                for field in protected:
                    values[field] = before[field]
            elif before and values.get("parse_status") != "detail_ready" and len(before["raw_text"] or "") > len(values.get("raw_text") or ""):
                # Legacy rows may still be marked `ok`, but their archived
                # detail body is valuable input for the migration/backfill.
                for field in ("raw_text", "role_text", "announcement_text", "role_signals", "field_evidence", "content_hash", "extraction_version"):
                    values[field] = before[field]
            conn.execute(
                f"""
                INSERT INTO jobs ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(dedupe_key) DO UPDATE SET {update_clause}
                """,
                values,
            )
            row = conn.execute("SELECT id FROM jobs WHERE dedupe_key = ?", (values["dedupe_key"],)).fetchone()
            job_id = int(row["id"])
            changed = before is None
            if before:
                visible_fields = (
                    "company", "title", "clean_title", "summary", "batch", "target_graduate_year",
                    "degree", "city", "deadline", "apply_url", "official_url", "raw_text",
                    "role_text", "announcement_text", "role_signals", "field_evidence",
                    "extraction_version", "parse_status", "content_hash",
                )
                changed = any(
                    before[field]
                    != (
                        before[field]
                        if field == "official_url" and not values.get(field)
                        else values.get(field)
                    )
                    for field in visible_fields
                )
                if changed:
                    conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (job_id,))
            return UpsertResult(job_id=job_id, created=before is None, changed=changed)

    def save_match(self, job_id: int, match: MatchResult | dict[str, Any]) -> None:
        data = asdict(match) if isinstance(match, MatchResult) else dict(match)
        values = {
            "job_id": job_id,
            "matched_keywords": self._join(data.get("matched_keywords", [])),
            "matched_strong_keywords": self._join(data.get("matched_strong_keywords", [])),
            "matched_weak_keywords": self._join(data.get("matched_weak_keywords", [])),
            "matched_industry_keywords": self._join(data.get("matched_industry_keywords", [])),
            "matched_company_rule": data.get("matched_company_rule", ""),
            "matched_city_rule": data.get("matched_city_rule", ""),
            "negative_keywords": self._join(data.get("negative_keywords", [])),
            "match_score": data.get("match_score", 0),
            "priority": data.get("priority", "D"),
            "is_relevant": int(bool(data.get("is_relevant", False))),
            "should_push": int(bool(data.get("should_push", False))),
            "needs_verify": int(bool(data.get("needs_verify", False))),
            "match_reason": data.get("match_reason", ""),
            "verify_status": data.get("verify_status", "未核验"),
            "suggested_search_terms": self._join(data.get("suggested_search_terms", [])),
            "match_config_version": data.get("match_config_version", ""),
            "matched_at": data.get("matched_at", ""),
            "recommend_reason": data.get("recommend_reason", ""),
        }
        columns = list(values)
        update_columns = [column for column in columns if column != "job_id"]
        placeholders = ", ".join(f":{column}" for column in columns)
        update_clause = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
        with self.connect() as conn:
            before = conn.execute("SELECT verify_status FROM job_matches WHERE job_id = ?", (job_id,)).fetchone()
            conn.execute(
                f"""
                INSERT INTO job_matches ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(job_id) DO UPDATE SET
                {update_clause}
                """,
                values,
            )
            if before and before["verify_status"] != values.get("verify_status", "未核验"):
                conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (job_id,))

    def get_job_with_match(self, job_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT jobs.*, job_matches.*,
                       COALESCE(job_user_state.status, '未看') AS user_status,
                       COALESCE(job_user_state.note, '') AS note,
                       COALESCE(job_user_state.apply_url_manual, '') AS apply_url_manual,
                       COALESCE(job_user_state.next_action, '') AS next_action
                FROM jobs
                LEFT JOIN job_matches ON jobs.id = job_matches.job_id
                LEFT JOIN job_user_state ON jobs.id = job_user_state.job_id
                WHERE jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else {}

    def list_jobs_with_matches(self, only_unsynced: bool = False) -> list[dict[str, Any]]:
        query = """
            SELECT jobs.*, job_matches.*, feishu_sync.sync_status
            FROM jobs
            LEFT JOIN job_matches ON jobs.id = job_matches.job_id
            LEFT JOIN feishu_sync ON jobs.id = feishu_sync.job_id
        """
        if only_unsynced:
            query += " WHERE feishu_sync.sync_status IS NULL OR feishu_sync.sync_status IN ('pending', 'failed')"
        query += " ORDER BY (jobs.collected_date IS NULL), jobs.collected_date DESC, jobs.id ASC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def list_stored_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM jobs
                    ORDER BY (collected_date IS NULL), collected_date DESC, id ASC
                    """
                ).fetchall()
            ]

    def get_stored_job(self, job_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def job_from_row(row: dict[str, Any]) -> Job:
        split = lambda value: [part for part in str(value).split(";") if part] if value else []
        fields = Job.__dataclass_fields__
        values = {name: row.get(name) for name in fields if name in row}
        for name in ("tags", "job_tags", "special_marks", "raw_tags", "role_signals"):
            values[name] = split(row.get(name))
        values["source"] = values.get("source") or "WonderCV"
        values["company"] = values.get("company") or ""
        values["title"] = values.get("title") or ""
        values["parse_status"] = values.get("parse_status") or "ok"
        values["is_active"] = int(values.get("is_active") if values.get("is_active") is not None else 1)
        return Job(**values)

    def list_all_jobs(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(self._all_jobs_query()).fetchall()]

    def list_feishu_sync_candidates(self) -> list[dict[str, Any]]:
        """Return only jobs that belong in the user-facing Feishu workspace."""
        tracked_statuses = ("收藏", "已投递", "笔试中", "面试中", "Offer", "已结束")
        placeholders = ", ".join("?" for _ in tracked_statuses)
        query = self._all_jobs_query(
            f"WHERE latest_recommendation.id IS NOT NULL OR job_user_state.status IN ({placeholders})"
        )
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, tracked_statuses).fetchall()]

    def list_feishu_reconciliation_rows(self) -> list[dict[str, Any]]:
        """Return every row that may require a create, update, or safe deactivation."""
        tracked_statuses = ("收藏", "已投递", "笔试中", "面试中", "Offer", "已结束")
        placeholders = ", ".join("?" for _ in tracked_statuses)
        query = self._all_jobs_query(
            f"""
            WHERE latest_recommendation.id IS NOT NULL
               OR job_user_state.status IN ({placeholders})
               OR feishu_sync.feishu_record_id IS NOT NULL
            """
        )
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(query, tracked_statuses).fetchall()]
        for row in rows:
            row["recommendation_active"] = bool(row["recommendation_active"])
        return rows

    def list_daily_new_jobs(self, date: str) -> list[dict[str, Any]]:
        query = self._all_jobs_query(
            """
            WHERE COALESCE(date(jobs.first_seen), jobs.collected_date) = ?
            """
        )
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, (date,)).fetchall()]

    def append_recommendations(self, recommendation_date: str, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            for row in rows:
                exists = conn.execute("SELECT 1 FROM recommended_jobs WHERE recommendation_date = ? AND job_id = ?", (recommendation_date, int(row["job_id"]))).fetchone()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO recommended_jobs
                        (recommendation_date, job_id, recommend_reason, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (recommendation_date, int(row["job_id"]), str(row.get("recommend_reason") or "")),
                )
                if not exists:
                    conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (int(row["job_id"]),))

    def replace_recommendations(self, recommendation_date: str, rows: Iterable[dict[str, Any]]) -> None:
        with self.connect() as conn:
            old_job_ids = [r[0] for r in conn.execute("SELECT job_id FROM recommended_jobs WHERE recommendation_date = ?", (recommendation_date,)).fetchall()]
            conn.execute("DELETE FROM recommended_jobs WHERE recommendation_date = ?", (recommendation_date,))
            new_job_ids = []
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO recommended_jobs
                        (recommendation_date, job_id, recommend_reason, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (recommendation_date, int(row["job_id"]), str(row.get("recommend_reason") or "")),
                )
                new_job_ids.append(int(row["job_id"]))
            changed_job_ids = set(old_job_ids) ^ set(new_job_ids)
            for job_id in changed_job_ids:
                conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (job_id,))

    def sync_global_recommendations(self, target_date: str, recommendations: Iterable[dict[str, Any]]) -> None:
        new_rec_map = {int(r["job_id"]): r.get("recommend_reason") or "" for r in recommendations}
        with self.connect() as conn:
            # Get current global recommendations
            old_job_ids = {
                r[0]
                for r in conn.execute("SELECT job_id FROM recommended_jobs").fetchall()
            }
            
            # 1. Deletions: in old_job_ids but not in new_rec_map
            to_delete = old_job_ids - set(new_rec_map.keys())
            for job_id in to_delete:
                conn.execute("DELETE FROM recommended_jobs WHERE job_id = ?", (job_id,))
                conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (job_id,))
                
            # 2. Additions: in new_rec_map but not in old_job_ids
            to_add = set(new_rec_map.keys()) - old_job_ids
            for job_id in to_add:
                conn.execute(
                    """
                    INSERT INTO recommended_jobs (recommendation_date, job_id, recommend_reason, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (target_date, job_id, new_rec_map[job_id]),
                )
                conn.execute("UPDATE feishu_sync SET sync_status = 'pending' WHERE job_id = ?", (job_id,))

    def list_recommended_jobs(self, recommendation_date: str | None = None) -> list[dict[str, Any]]:
        where = ""
        params: tuple[Any, ...] = ()
        if recommendation_date:
            where = "WHERE COALESCE(jobs.collected_date, recommended_jobs.recommendation_date) = ?"
            params = (recommendation_date,)
        query = f"""
            SELECT
                COALESCE(jobs.collected_date, recommended_jobs.recommendation_date) AS feishu_collected_date,
                recommended_jobs.job_id,
                jobs.company,
                COALESCE(jobs.clean_title, jobs.title) AS title,
                jobs.batch,
                jobs.target_graduate_year,
                jobs.city,
                jobs.summary,
                recommended_jobs.recommend_reason,
                COALESCE(jobs.detail_url, jobs.source_url) AS original_url,
                jobs.apply_url,
                jobs.official_url,
                COALESCE(job_matches.verify_status, '') AS verify_status,
                COALESCE(job_user_state.status, '未看') AS user_status,
                COALESCE(job_user_state.note, '') AS note
            FROM recommended_jobs
            JOIN jobs ON recommended_jobs.job_id = jobs.id
            LEFT JOIN job_matches ON jobs.id = job_matches.job_id
            LEFT JOIN job_user_state ON jobs.id = job_user_state.job_id
            {where}
            ORDER BY recommended_jobs.recommendation_date DESC, recommended_jobs.id ASC
        """
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    @staticmethod
    def _all_jobs_query(where: str = "") -> str:
        return f"""
            SELECT
                jobs.id AS job_id,
                jobs.source,
                jobs.company,
                COALESCE(jobs.clean_title, jobs.title) AS title,
                jobs.summary,
                jobs.batch,
                jobs.target_graduate_year,
                jobs.degree,
                jobs.city,
                jobs.collected_date,
                jobs.deadline,
                jobs.industry,
                jobs.company_type,
                jobs.job_tags,
                jobs.special_marks,
                COALESCE(jobs.detail_url, jobs.source_url) AS original_url,
                jobs.apply_url,
                jobs.official_url,
                jobs.first_seen,
                jobs.last_seen,
                COALESCE(job_matches.verify_status, '') AS verify_status,
                CASE WHEN latest_recommendation.id IS NULL THEN '不推荐' ELSE '推荐' END AS recommendation_status,
                CASE WHEN latest_recommendation.id IS NULL THEN 0 ELSE 1 END AS recommendation_active,
                CASE WHEN latest_recommendation.id IS NULL THEN NULL ELSE latest_recommendation.recommendation_date END AS recommendation_date,
                COALESCE(jobs.collected_date, latest_recommendation.recommendation_date) AS feishu_collected_date,
                COALESCE(latest_recommendation.recommend_reason, '') AS recommend_reason,
                COALESCE(job_matches.match_reason, '') AS non_recommend_reason,
                COALESCE(job_matches.negative_keywords, '') AS excluded_keywords,
                COALESCE(job_user_state.status, '未看') AS user_status,
                COALESCE(job_user_state.next_action, '') AS next_action,
                COALESCE(job_user_state.note, '') AS note,
                feishu_sync.feishu_record_id,
                feishu_sync.sync_status
            FROM jobs
            LEFT JOIN job_matches ON jobs.id = job_matches.job_id
            LEFT JOIN job_user_state ON jobs.id = job_user_state.job_id
            LEFT JOIN recommended_jobs latest_recommendation ON latest_recommendation.id = (
                SELECT recommended_jobs.id
                FROM recommended_jobs
                WHERE recommended_jobs.job_id = jobs.id
                ORDER BY recommended_jobs.recommendation_date DESC, recommended_jobs.id DESC
                LIMIT 1
            )
            LEFT JOIN feishu_sync ON jobs.id = feishu_sync.job_id
            {where}
            ORDER BY (jobs.collected_date IS NULL), jobs.collected_date DESC, jobs.id ASC
        """

    def job_exists(self, dedupe_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM jobs WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            return row is not None

    def job_requires_detail_enrichment(self, dedupe_key: str, extraction_version: str) -> bool:
        """Whether a known list card must still be fetched instead of triggering early stop."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT parse_status, extraction_version FROM jobs WHERE dedupe_key = ?", (dedupe_key,)
            ).fetchone()
        return bool(
            row
            and (
                row["parse_status"] != "detail_ready"
                or row["extraction_version"] != extraction_version
            )
        )

    def update_official_url_if_empty(self, job_id: int, official_url: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT official_url FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or row["official_url"]:
                return False
            conn.execute("UPDATE jobs SET official_url = ? WHERE id = ?", (official_url, job_id))
            conn.execute(
                """
                INSERT INTO feishu_sync (job_id, sync_status)
                VALUES (?, 'pending')
                ON CONFLICT(job_id) DO UPDATE SET sync_status = 'pending'
                """,
                (job_id,),
            )
            return True

    def get_last_successful_run_date(self, run_type: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT date(started_at) as run_date
                FROM scan_runs
                WHERE run_type = ? AND status = 'success'
                ORDER BY id DESC LIMIT 1
                """,
                (run_type,),
            ).fetchone()
            return row["run_date"] if row else None

    def count_jobs(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def vacuum(self) -> None:
        with self.connect() as conn:
            conn.execute("VACUUM")

    def record_scan_run(self, values: dict[str, Any]) -> None:
        columns = list(values)
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO scan_runs ({', '.join(columns)}) VALUES ({', '.join(f':{c}' for c in columns)})",
                values,
            )

    def mark_sync(self, job_id: int, status: str, record_id: str | None = None, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feishu_sync (job_id, feishu_record_id, last_synced_at, sync_status, sync_error)
                VALUES (?, ?, datetime('now'), ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    feishu_record_id=excluded.feishu_record_id,
                    last_synced_at=excluded.last_synced_at,
                    sync_status=excluded.sync_status,
                    sync_error=excluded.sync_error
                """,
                (job_id, record_id, status, error),
            )

    def sync_job_ids_by_record_id(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT job_id, feishu_record_id FROM feishu_sync WHERE feishu_record_id IS NOT NULL AND feishu_record_id != ''"
            ).fetchall()
        return {str(row["feishu_record_id"]): int(row["job_id"]) for row in rows}

    def clear_feishu_sync(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM feishu_sync")

    def update_user_state(
        self,
        job_id: int,
        status: str,
        note: str,
        official_url: str | None = None,
        apply_url_manual: str | None = None,
        next_action: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_user_state (job_id, status, note, official_url, apply_url_manual, next_action, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    note=excluded.note,
                    official_url=COALESCE(excluded.official_url, job_user_state.official_url),
                    apply_url_manual=COALESCE(excluded.apply_url_manual, job_user_state.apply_url_manual),
                    next_action=COALESCE(excluded.next_action, job_user_state.next_action),
                    updated_at=excluded.updated_at
                """,
                (job_id, status, note, official_url, apply_url_manual, next_action),
            )

    @staticmethod
    def _join(value: Iterable[str] | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return ";".join(str(item) for item in value)

