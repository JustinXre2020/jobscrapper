"""
Database module for job deduplication and persistence.
Uses Redis when REDIS_PORT is configured; falls back to a text file otherwise.
"""
import os
import json

from loguru import logger
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timezone
import redis as redis_lib

from utils.config import settings

_REDIS_TTL = 259200  # 3 days in seconds (jobdedup: seen-recently cache)
_DEDUP_PREFIX = "jobdedup:"   # ephemeral: seen in last 3 days
_SENT_PREFIX = "jobsent:"     # permanent: successfully emailed

# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


class JobDatabase:
    """Job dedup/persistence handler.

    When ``REDIS_PORT`` is set, all operations go through Redis:
      - ``jobdedup:<url>``  (string, 3-day TTL)
      - ``jobsent:<url>``   (hash, 3-day TTL)

    When Redis is not configured, falls back to ``sent_jobs.txt``.
    """

    def __init__(self, database_url: Optional[str] = None):  # database_url kept for API compat
        self.fallback_file = str(DATA_DIR / "sent_jobs.txt")
        self.redis_client = self._init_redis()

        if self.redis_client is None:
            if not os.path.exists(self.fallback_file):
                with open(self.fallback_file, "w") as f:
                    f.write("")
            logger.info("📝 Redis not configured — using text-file dedup fallback")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_redis(self):
        """Return a connected Redis client, or None if REDIS_PORT is unset."""
        redis_host = settings.REDIS_HOST
        if not redis_host:
            return None
        try:
            redis_port = settings.REDIS_PORT
            client = redis_lib.Redis(host=redis_host, port=int(redis_port), socket_timeout=3)
            client.ping()
            logger.info(f"✅ Redis initialized: {redis_host}:{redis_port}")
            return client
        except Exception as e:
            logger.warning(f"⚠️ Redis init failed, using text-file fallback: {e}")
            return None

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def is_job_sent(self, job_url: str) -> bool:
        """Return True if *job_url* was previously marked as sent."""
        if self.redis_client is not None:
            try:
                return bool(self.redis_client.exists(f"{_SENT_PREFIX}{job_url}"))
            except Exception as e:
                logger.warning(f"⚠️ Redis is_job_sent error: {e}")
        return self._is_job_sent_fallback(job_url)

    def _is_job_sent_fallback(self, job_url: str) -> bool:
        try:
            with open(self.fallback_file, "r") as f:
                return job_url in {line.strip() for line in f if line.strip()}
        except Exception as e:
            logger.error(f"❌ Fallback file read error: {e}")
            return False

    def mark_as_sent(
        self,
        job_url: str,
        title: str = "",
        company: str = "",
        location: str = "",
        score: int = 0,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """Persist job_url as sent (with optional metadata)."""
        if self.redis_client is None:
            return self._mark_as_sent_fallback(job_url)
        try:
            key = f"{_SENT_PREFIX}{job_url}"
            if self.redis_client.exists(key):
                logger.info(f"⚠️ Already marked as sent: {job_url}")
                return True
            mapping = {
                "title": title,
                "company": company,
                "location": location,
                "score": str(score),
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "metadata": json.dumps(metadata) if metadata else "",
            }
            # HSET + EXPIRE in a single pipeline round-trip
            pipe = self.redis_client.pipeline()
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, _REDIS_TTL)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"❌ Redis mark_as_sent error: {e}")

    def _mark_as_sent_fallback(self, job_url: str) -> bool:
        try:
            with open(self.fallback_file, "a") as f:
                f.write(f"{job_url}\n")
            return True
        except Exception as e:
            logger.error(f"❌ Fallback file write error: {e}")
            return False

    def get_sent_jobs(self, limit: int = 100) -> List[Dict]:
        """Return up to *limit* recently sent jobs (most recent first)."""
        if self.redis_client is None:
            return self._get_sent_jobs_fallback(limit)
        try:
            keys = []
            cursor = 0
            while True:
                cursor, batch = self.redis_client.scan(
                    cursor, match=f"{_SENT_PREFIX}*", count=500
                )
                keys.extend(batch)
                if cursor == 0:
                    break

            results = []
            for key in keys:
                data = self.redis_client.hgetall(key)
                if data:
                    job_url = key.decode().removeprefix(_SENT_PREFIX)
                    results.append(
                        {
                            "job_url": job_url,
                            "title": data.get(b"title", b"").decode(),
                            "company": data.get(b"company", b"").decode(),
                            "location": data.get(b"location", b"").decode(),
                            "score": int(data.get(b"score", b"0").decode() or 0),
                            "sent_at": data.get(b"sent_at", b"").decode(),
                            "metadata": json.loads(data[b"metadata"].decode())
                            if data.get(b"metadata")
                            else None,
                        }
                    )

            results.sort(key=lambda j: j["sent_at"], reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error(f"❌ Redis get_sent_jobs error: {e}")
            return []

    def _get_sent_jobs_fallback(self, limit: int) -> List[Dict]:
        try:
            with open(self.fallback_file, "r") as f:
                urls = [line.strip() for line in f if line.strip()]
            return [{"job_url": url} for url in urls[-limit:]]
        except Exception as e:
            logger.error(f"❌ Fallback file read error: {e}")
            return []

    def filter_new_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filter out jobs already seen or sent.

        With Redis:
          1. Check ``jobdedup:<url>`` (3-day TTL). If present → skip.
          2. Set ``jobdedup:<url>`` (3-day TTL) so the same job is not
             re-processed by the LLM within the same window.
          3. Check ``jobsent:<url>`` (permanent). If present → skip.
          4. Otherwise → include in returned list.

        Without Redis: checks the text-file fallback only.
        """
        new_jobs = []

        for job in jobs:
            job_url = job.get("job_url") or job.get("job_data", {}).get("job_url")

            if not job_url:
                logger.warning("⚠️ Job missing job_url, skipping")
                continue

            if self.redis_client is not None:
                try:
                    dedup_key = f"{_DEDUP_PREFIX}{job_url}"
                    if self.redis_client.exists(dedup_key):
                        logger.info(
                            f"⏭️ Redis recent-seen duplicate: "
                            f"{job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}"
                        )
                        continue
                    # Mark as seen for 3 days to avoid LLM re-processing
                    self.redis_client.set(dedup_key, "1", ex=_REDIS_TTL)
                except Exception as e:
                    logger.warning(f"⚠️ Redis dedup check failed, continuing: {e}")

            if not self.is_job_sent(job_url):
                new_jobs.append(job)
            else:
                logger.debug(
                    f"⏭️ Skipping sent duplicate: "
                    f"{job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}"
                )

        logger.info(f"🆕 {len(new_jobs)}/{len(jobs)} new jobs to process")
        return new_jobs

    def cleanup_old_records(self, days: int = 90):
        """Delete ``jobsent:`` keys whose ``sent_at`` is older than *days* days."""
        if self.redis_client is None:
            logger.warning("⚠️ Cleanup only available when Redis is configured")
            return
        try:
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            deleted = 0
            cursor = 0
            while True:
                cursor, batch = self.redis_client.scan(
                    cursor, match=f"{_SENT_PREFIX}*", count=500
                )
                for key in batch:
                    sent_at_raw = self.redis_client.hget(key, "sent_at")
                    if sent_at_raw:
                        try:
                            sent_at = datetime.fromisoformat(sent_at_raw.decode())
                            if sent_at.tzinfo is None:
                                sent_at = sent_at.replace(tzinfo=timezone.utc)
                            if sent_at < cutoff:
                                self.redis_client.delete(key)
                                deleted += 1
                        except ValueError:
                            pass
                if cursor == 0:
                    break
            logger.info(f"🗑️ Cleaned up {deleted} old records (older than {days} days)")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
