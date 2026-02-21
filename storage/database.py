"""
Database module for job deduplication and persistence
Supports both SQLite and text file storage
"""
import os
import json
from loguru import logger
from pathlib import Path
from typing import Set, Optional, Dict, List
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()


# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

Base = declarative_base()


class SentJob(Base):
    """SQLAlchemy model for sent jobs tracking"""
    __tablename__ = 'sent_jobs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_url = Column(String, unique=True, nullable=False, index=True)
    title = Column(String)
    company = Column(String)
    location = Column(String)
    score = Column(Integer)
    sent_at = Column(DateTime, default=datetime.utcnow)
    job_metadata = Column(Text)  # JSON string for additional data
    
    def __repr__(self):
        return f"<SentJob(url='{self.job_url}', title='{self.title}', company='{self.company}')>"


class JobDatabase:
    """Database handler with fallback to text file"""
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database connection

        Args:
            database_url: SQLAlchemy connection string or path
        """
        # Default to data/ directory for SQLite
        default_db = f"sqlite:///{DATA_DIR / 'jobs.db'}"
        self.database_url = database_url or os.getenv("DATABASE_URL", default_db)
        self.use_sqlite = self.database_url.startswith("sqlite")
        self.fallback_file = str(DATA_DIR / "sent_jobs.txt")
        
        try:
            # Try to initialize SQLAlchemy
            self.engine = create_engine(self.database_url)
            Base.metadata.create_all(self.engine)
            self.SessionLocal = sessionmaker(bind=self.engine)
            self.db_available = True
            logger.info(f"✅ Database initialized: {self.database_url}")

        except Exception as e:
            logger.warning(f"⚠️ Database initialization failed: {e}")
            logger.info(f"📝 Falling back to text file: {self.fallback_file}")
            self.db_available = False
            
            # Ensure fallback file exists
            if not os.path.exists(self.fallback_file):
                with open(self.fallback_file, 'w') as f:
                    f.write("")
    
    def _get_session(self) -> Optional[Session]:
        """Get database session if available"""
        if self.db_available:
            return self.SessionLocal()
        return None
    
    def is_job_sent(self, job_url: str) -> bool:
        """
        Check if a job has already been sent
        
        Args:
            job_url: Unique job URL identifier
            
        Returns:
            True if job was already sent, False otherwise
        """
        if self.db_available:
            session = self._get_session()
            try:
                exists = session.query(SentJob).filter_by(job_url=job_url).first() is not None
                return exists
            except Exception as e:
                logger.error(f"❌ Database query error: {e}")
                return self._is_job_sent_fallback(job_url)
            finally:
                session.close()
        else:
            return self._is_job_sent_fallback(job_url)
    
    def _is_job_sent_fallback(self, job_url: str) -> bool:
        """Check if job was sent using text file"""
        try:
            with open(self.fallback_file, 'r') as f:
                sent_urls = set(line.strip() for line in f if line.strip())
                return job_url in sent_urls
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
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Mark a job as sent
        
        Args:
            job_url: Unique job URL
            title: Job title
            company: Company name
            location: Job location
            score: AI score
            metadata: Additional data as dict
            
        Returns:
            True if successful, False otherwise
        """
        if self.db_available:
            session = self._get_session()
            try:
                # Check if already exists
                existing = session.query(SentJob).filter_by(job_url=job_url).first()
                if existing:
                    logger.debug(f"⚠️ Job already marked as sent: {job_url}")
                    return True
                
                # Create new record
                sent_job = SentJob(
                    job_url=job_url,
                    title=title,
                    company=company,
                    location=location,
                    score=score,
                    job_metadata=json.dumps(metadata) if metadata else None
                )
                
                session.add(sent_job)
                session.commit()
                return True
                
            except Exception as e:
                logger.error(f"❌ Database insert error: {e}")
                session.rollback()
                return self._mark_as_sent_fallback(job_url)
            finally:
                session.close()
        else:
            return self._mark_as_sent_fallback(job_url)
    
    def _mark_as_sent_fallback(self, job_url: str) -> bool:
        """Mark job as sent using text file"""
        try:
            with open(self.fallback_file, 'a') as f:
                f.write(f"{job_url}\n")
            return True
        except Exception as e:
            logger.error(f"❌ Fallback file write error: {e}")
            return False
    
    def get_sent_jobs(self, limit: int = 100) -> List[Dict]:
        """
        Retrieve recently sent jobs
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of job dicts
        """
        if self.db_available:
            session = self._get_session()
            try:
                jobs = session.query(SentJob)\
                    .order_by(SentJob.sent_at.desc())\
                    .limit(limit)\
                    .all()
                
                return [
                    {
                        "job_url": job.job_url,
                        "title": job.title,
                        "company": job.company,
                        "location": job.location,
                        "score": job.score,
                        "sent_at": job.sent_at.isoformat() if job.sent_at else None,
                        "metadata": json.loads(job.job_metadata) if job.job_metadata else None
                    }
                    for job in jobs
                ]
            except Exception as e:
                logger.error(f"❌ Database query error: {e}")
                return []
            finally:
                session.close()
        else:
            return self._get_sent_jobs_fallback(limit)

    def _get_sent_jobs_fallback(self, limit: int) -> List[Dict]:
        """Get sent jobs from text file"""
        try:
            with open(self.fallback_file, 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
                return [{"job_url": url} for url in urls[-limit:]]
        except Exception as e:
            logger.error(f"❌ Fallback file read error: {e}")
            return []
    
    def filter_new_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """
        Filter out jobs that have already been sent
        
        Args:
            jobs: List of job dicts with 'job_url' key
            
        Returns:
            List of new jobs only
        """
        new_jobs = []
        
        for job in jobs:
            job_url = job.get('job_url') or job.get('job_data', {}).get('job_url')
            
            if not job_url:
                logger.warning("⚠️ Job missing job_url, skipping")
                continue

            if not self.is_job_sent(job_url):
                new_jobs.append(job)
            else:
                logger.debug(f"⏭️ Skipping duplicate: {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}")

        logger.info(f"🆕 {len(new_jobs)}/{len(jobs)} new jobs to send")
        return new_jobs
    
    def cleanup_old_records(self, days: int = 90):
        """
        Remove records older than specified days (SQLite only)
        
        Args:
            days: Keep records newer than this many days
        """
        if not self.db_available:
            logger.warning("⚠️ Cleanup only available for database mode")
            return

        session = self._get_session()
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            deleted = session.query(SentJob)\
                .filter(SentJob.sent_at < cutoff_date)\
                .delete()

            session.commit()
            logger.info(f"🗑️ Cleaned up {deleted} old records (older than {days} days)")

        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
            session.rollback()
        finally:
            session.close()


def main():
    """Test the database"""
    db = JobDatabase()
    
    # Test job
    test_url = "https://example.com/job/12345"
    test_job = {
        "job_url": test_url,
        "title": "Senior Engineer",
        "company": "Tech Corp",
        "location": "San Francisco, CA",
        "score": 8
    }
    
    # Check if exists
    print(f"\n1. Checking if job exists: {db.is_job_sent(test_url)}")
    
    # Mark as sent
    print(f"\n2. Marking job as sent...")
    db.mark_as_sent(**test_job)
    
    # Check again
    print(f"\n3. Checking if job exists: {db.is_job_sent(test_url)}")
    
    # Get recent jobs
    print(f"\n4. Recent sent jobs:")
    recent = db.get_sent_jobs(limit=5)
    for job in recent:
        print(f"   - {job.get('title', 'N/A')} at {job.get('company', 'N/A')}")


if __name__ == "__main__":
    main()
