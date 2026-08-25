"""
Jarvis Bookkeeping Service — Local SQLite Storage (Phase 6.2)
=============================================================
Manages table initialization, schema migration, and non-blocking usage recording
for LLM invocations and external provider calls.

Hard Task additions:
  - Auto-period advancement: when today > period_start + 30 days, auto-rolls the period
  - update_provider_quota(): update limits/period_start in DB at runtime (no code edits)
  - get_all_providers_quota_status(): single call for all providers
  - get_recent_provider_usage() / get_recent_llm_usage(): timeline queries for the UI
  - get_usage_for_period(): arbitrary date-range query
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from config.bookkeeping_settings import BOOKKEEPING_DB_PATH, PROVIDER_QUOTAS

logger = logging.getLogger("jarvis.bookkeeping")

# Default billing period length (days) used by auto-advancement
DEFAULT_PERIOD_DAYS = 30


class BookkeepingService:
    """
    Lightweight SQLite usage database observer. Non-critical background operations.
    """

    def __init__(self, db_path: Path = BOOKKEEPING_DB_PATH):
        self.db_path = Path(db_path)
        self._ensure_db_dir()
        self.init_db()

    def _ensure_db_dir(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to create database directory: {e}")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize database schema and seed default provider quota configurations."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Table 1: LLM Usage Log
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS llm_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        model TEXT NOT NULL,
                        role TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        total_tokens INTEGER,
                        duration_ms INTEGER,
                        error_info TEXT
                    );
                """)

                # Table 2: Provider Usage Log
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS provider_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        request_count INTEGER DEFAULT 1,
                        estimated_count INTEGER DEFAULT 1,
                        duration_ms INTEGER,
                        error_info TEXT,
                        metadata TEXT
                    );
                """)

                # Table 3: Provider Quota Configs
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS provider_quotas (
                        provider TEXT PRIMARY KEY,
                        quota_limit INTEGER NOT NULL,
                        baseline_used INTEGER NOT NULL DEFAULT 0,
                        period_start TEXT NOT NULL,
                        period_end TEXT,
                        updated_at TEXT NOT NULL
                    );
                """)

                # Add the one-time pre-bookkeeping usage offset to existing databases.
                columns = {row["name"] for row in cursor.execute("PRAGMA table_info(provider_quotas)")}
                if "baseline_used" not in columns:
                    cursor.execute("ALTER TABLE provider_quotas ADD COLUMN baseline_used INTEGER NOT NULL DEFAULT 0")

                # Seed/sync default provider quota configs if not existing
                now_str = datetime.now(timezone.utc).isoformat()
                for provider, config in PROVIDER_QUOTAS.items():
                    cursor.execute("""
                        INSERT INTO provider_quotas (provider, quota_limit, period_start, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(provider) DO NOTHING;
                    """, (provider, config["quota_limit"], config["period_start"], now_str))

                conn.commit()
                logger.info(f"[BOOKKEEPING] Initialized SQLite database at {self.db_path}")

        except Exception as e:
            logger.error(f"[BOOKKEEPING] Database initialization error: {e}")

    # ---------------------------------------------------------------------------
    # Period Advancement Logic (Hard Task)
    # ---------------------------------------------------------------------------

    def _advance_period_if_needed(self, provider: str, period_start_str: str, conn: sqlite3.Connection) -> str:
        """
        Auto-advance the billing period if today has moved past period_start + DEFAULT_PERIOD_DAYS.
        Returns the current (possibly newly advanced) period_start string.
        This ensures quota usage resets correctly without manual code changes.
        """
        try:
            # Support both date-only (YYYY-MM-DD) and ISO datetime formats
            if "T" in period_start_str:
                period_start = datetime.fromisoformat(period_start_str).replace(tzinfo=timezone.utc)
            else:
                period_start = datetime.strptime(period_start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

            today = datetime.now(timezone.utc)
            period_length = timedelta(days=DEFAULT_PERIOD_DAYS)

            # Advance in multiples of period_length until period_start is within the current cycle
            if today >= period_start + period_length:
                new_start = period_start
                while today >= new_start + period_length:
                    new_start += period_length

                new_start_str = new_start.strftime("%Y-%m-%d")
                now_str = today.isoformat()

                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE provider_quotas SET period_start = ?, baseline_used = 0, updated_at = ?
                    WHERE provider = ?;
                """, (new_start_str, now_str, provider))
                conn.commit()

                logger.info(f"[BOOKKEEPING] Auto-advanced period for '{provider}': {period_start_str} → {new_start_str}")
                return new_start_str

        except Exception as e:
            logger.warning(f"[BOOKKEEPING] Period advancement failed for '{provider}': {e}")

        return period_start_str

    # ---------------------------------------------------------------------------
    # Recording Functions (Non-blocking / Defensive)
    # ---------------------------------------------------------------------------

    def record_llm_usage(
        self,
        model: str,
        role: str,
        success: bool = True,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        duration_ms: Optional[int] = None,
        error_info: Optional[str] = None,
    ) -> None:
        """Record an LLM invocation (Router, Worker, or Fallback)."""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO llm_usage (
                        timestamp, model, role, success, prompt_tokens,
                        completion_tokens, total_tokens, duration_ms, error_info
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    timestamp, model, role, 1 if success else 0,
                    prompt_tokens, completion_tokens, total_tokens,
                    duration_ms, error_info
                ))
                conn.commit()
            logger.info(f"[BOOKKEEPING] {role.capitalize()} LLM usage recorded: {model}")
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to record LLM usage: {e}")

    def record_provider_usage(
        self,
        provider: str,
        operation: str,
        success: bool = True,
        request_count: int = 1,
        estimated_count: int = 1,
        duration_ms: Optional[int] = None,
        error_info: Optional[str] = None,
        metadata: Optional[str] = None,
    ) -> None:
        """Record an external provider operation (e.g. Exa, Tavily, Firecrawl)."""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO provider_usage (
                        timestamp, provider, operation, success, request_count,
                        estimated_count, duration_ms, error_info, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    timestamp, provider, operation, 1 if success else 0,
                    request_count, estimated_count, duration_ms,
                    error_info, metadata
                ))
                conn.commit()
            logger.info(f"[BOOKKEEPING] Provider usage recorded: {provider} ({operation})")
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to record provider usage: {e}")

    # ---------------------------------------------------------------------------
    # Quota Management (Hard Task) — update at runtime without code changes
    # ---------------------------------------------------------------------------

    def update_provider_quota(
        self,
        provider: str,
        quota_limit: Optional[int] = None,
        period_start: Optional[str] = None,
        baseline_used: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update a provider's quota, period, and optional starting usage in the DB at runtime.
        Called by the REST API — no source code edit required.
        Returns the updated quota status dict.
        """
        try:
            now_str = datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Upsert: create the row if the provider isn't seeded yet
                cursor.execute("""
                    INSERT INTO provider_quotas (provider, quota_limit, baseline_used, period_start, updated_at)
                    VALUES (?, COALESCE(?, 1000), COALESCE(?, 0), COALESCE(?, date('now')), ?)
                    ON CONFLICT(provider) DO UPDATE SET
                        quota_limit = COALESCE(?, quota_limit),
                        baseline_used = COALESCE(?, baseline_used),
                        period_start = COALESCE(?, period_start),
                        updated_at = ?;
                """, (
                    provider,
                    quota_limit, baseline_used, period_start, now_str,
                    quota_limit, baseline_used, period_start, now_str,
                ))
                conn.commit()

            logger.info(f"[BOOKKEEPING] Updated quota for '{provider}': limit={quota_limit}, baseline={baseline_used}, period_start={period_start}")
            return self.get_provider_usage(provider)

        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to update provider quota: {e}")
            return {"error": str(e)}

    # ---------------------------------------------------------------------------
    # Query Functions (Internal Service API)
    # ---------------------------------------------------------------------------

    def get_provider_usage(self, provider: str) -> Dict[str, Any]:
        """Get aggregate usage and quota calculations for a single provider, with auto-period-advance."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT quota_limit, baseline_used, period_start FROM provider_quotas WHERE provider = ?;", (provider,))
                quota_row = cursor.fetchone()

                if not quota_row:
                    limit = 1000
                    baseline_used = 0
                    period_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                else:
                    limit = quota_row["quota_limit"]
                    baseline_used = quota_row["baseline_used"] or 0
                    period_start = quota_row["period_start"]

                # Hard Task: auto-advance the billing period if it has rolled over
                period_start = self._advance_period_if_needed(provider, period_start, conn)

                cursor.execute("""
                    SELECT SUM(request_count) as total_requests
                    FROM provider_usage
                    WHERE provider = ? AND timestamp >= ? AND success = 1;
                """, (provider, period_start))
                usage_row = cursor.fetchone()
                recorded = usage_row["total_requests"] if usage_row and usage_row["total_requests"] else 0
                used = baseline_used + recorded

                remaining = max(0, limit - used)
                percentage_used = round((used / limit * 100), 2) if limit > 0 else 0.0

                return {
                    "provider": provider,
                    "quota_limit": limit,
                    "baseline_used": baseline_used,
                    "period_start": period_start,
                    "used": used,
                    "remaining": remaining,
                    "percentage_used": percentage_used,
                }
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get provider usage: {e}")
            return {"provider": provider, "quota_limit": 0, "period_start": "", "used": 0, "remaining": 0, "percentage_used": 0.0}

    def get_all_providers_quota_status(self) -> List[Dict[str, Any]]:
        """
        Hard Task: Single call returning quota status for ALL known providers.
        Covers DB-seeded providers plus any that appear in the usage log.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT provider FROM provider_quotas;")
                quota_providers = {row["provider"] for row in cursor.fetchall()}

                cursor.execute("SELECT DISTINCT provider FROM provider_usage;")
                usage_providers = {row["provider"] for row in cursor.fetchall()}

            all_providers = quota_providers | usage_providers
            return [self.get_provider_usage(p) for p in sorted(all_providers)]
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get all providers quota status: {e}")
            return []

    def get_llm_usage_summary(self) -> List[Dict[str, Any]]:
        """Aggregate summary of requests and token counts by role + model."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        role,
                        model,
                        COUNT(*) as request_count,
                        SUM(prompt_tokens) as total_prompt_tokens,
                        SUM(completion_tokens) as total_completion_tokens,
                        SUM(total_tokens) as total_tokens,
                        AVG(duration_ms) as avg_duration_ms
                    FROM llm_usage
                    GROUP BY role, model
                    ORDER BY role, request_count DESC;
                """)
                return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get LLM usage summary: {e}")
            return []

    def get_recent_provider_usage(self, provider: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Hard Task: Timeline query — recent individual provider operations.
        Optionally filtered by provider. Ordered newest-first.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if provider:
                    cursor.execute("""
                        SELECT timestamp, provider, operation, success,
                               request_count, estimated_count, duration_ms, error_info
                        FROM provider_usage WHERE provider = ?
                        ORDER BY timestamp DESC LIMIT ?;
                    """, (provider, limit))
                else:
                    cursor.execute("""
                        SELECT timestamp, provider, operation, success,
                               request_count, estimated_count, duration_ms, error_info
                        FROM provider_usage ORDER BY timestamp DESC LIMIT ?;
                    """, (limit,))
                return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get recent provider usage: {e}")
            return []

    def get_recent_llm_usage(self, role: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Hard Task: Timeline query — recent individual LLM invocations.
        Optionally filtered by role (router/worker/fallback). Ordered newest-first.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if role:
                    cursor.execute("""
                        SELECT timestamp, model, role, success,
                               prompt_tokens, completion_tokens, total_tokens, duration_ms
                        FROM llm_usage WHERE role = ?
                        ORDER BY timestamp DESC LIMIT ?;
                    """, (role, limit))
                else:
                    cursor.execute("""
                        SELECT timestamp, model, role, success,
                               prompt_tokens, completion_tokens, total_tokens, duration_ms
                        FROM llm_usage ORDER BY timestamp DESC LIMIT ?;
                    """, (limit,))
                return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get recent LLM usage: {e}")
            return []

    def get_usage_for_period(self, provider: str, from_date: str, to_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Hard Task: Arbitrary date-range query —
        'How much did provider X consume between two dates?'
        """
        try:
            to_date = to_date or datetime.now(timezone.utc).isoformat()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        provider,
                        SUM(request_count) as total_requests,
                        SUM(estimated_count) as total_estimated,
                        COUNT(*) as operations,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_count
                    FROM provider_usage
                    WHERE provider = ? AND timestamp >= ? AND timestamp <= ?;
                """, (provider, from_date, to_date))
                row = cursor.fetchone()
                d = dict(row) if row else {"provider": provider, "total_requests": 0, "operations": 0}
                d["from_date"] = from_date
                d["to_date"] = to_date
                return d
        except Exception as e:
            logger.error(f"[BOOKKEEPING] Failed to get period usage: {e}")
            return {"error": str(e)}


# Global singleton instance for easy import across modules
bookkeeping_service = BookkeepingService()
