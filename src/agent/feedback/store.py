"""JSONL persistence for reviewer corrections.

Stores feedback from the Reviewer node so future Analyzer prompts
can learn from past mistakes.

Also provides a factory function to create the appropriate store
(JSONL or Milvus vector) based on configuration.
"""

import json
from loguru import logger
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Union


DEFAULT_FEEDBACK_PATH = Path("data/reviewer_feedback.jsonl")
MAX_FEEDBACK_ENTRIES = 20


class FeedbackStore:
    """Read/write reviewer corrections to a JSONL file.

    Each line is a JSON object:
        {"timestamp": ..., "job_title": ..., "job_company": ..., "feedback": ...}
    """

    def __init__(self, path: Path = DEFAULT_FEEDBACK_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_feedback(self, max_entries: int = MAX_FEEDBACK_ENTRIES) -> List[str]:
        """Load the most recent correction strings.

        Args:
            max_entries: Maximum number of entries to return.

        Returns:
            List of feedback strings (most recent last).
        """
        if not self.path.exists():
            return []

        entries: List[str] = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        feedback = record.get("feedback", "")
                        if feedback:
                            entries.append(feedback)
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning(f"Could not read feedback file: {e}")
            return []

        # Return the most recent entries, capped
        return entries[-max_entries:]

    def save_feedback(
        self,
        feedback: str,
        job_title: str,
        job_company: str,
    ) -> None:
        """Append a reviewer correction to the feedback file.

        Args:
            feedback: The correction text from the Reviewer.
            job_title: Title of the job that was corrected.
            job_company: Company of the job that was corrected.
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_title": job_title,
            "job_company": job_company,
            "feedback": feedback,
        }

        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.info(
                f"Saved reviewer feedback for '{job_title} @ {job_company}'"
            )
        except OSError as e:
            logger.error(f"Could not write feedback file: {e}")


def create_feedback_store(embedding_client=None) -> Union["FeedbackStore", Any]:
    """Factory function to create the appropriate feedback store.

    When USE_VECTOR_FEEDBACK=true and an embedding_client is provided,
    returns a VectorFeedbackStore. Otherwise returns the JSONL-based FeedbackStore.

    Args:
        embedding_client: Optional EmbeddingClient for vector store.

    Returns:
        FeedbackStore or VectorFeedbackStore instance.
    """
    use_vector = os.getenv("USE_VECTOR_FEEDBACK", "false").lower() == "true"

    if use_vector and embedding_client is not None:
        try:
            from agent.feedback.vector_store import VectorFeedbackStore

            store = VectorFeedbackStore(embedding_client=embedding_client)
            logger.info("Using Milvus vector feedback store")
            return store
        except ImportError:
            logger.warning(
                "pymilvus or sentence-transformers not installed, "
                "falling back to JSONL feedback store"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize vector store: {e}, falling back to JSONL")

    logger.info("Using JSONL feedback store")
    return FeedbackStore()
