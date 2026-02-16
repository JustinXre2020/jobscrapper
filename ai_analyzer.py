"""
AI Analyzer using Gemini API
Evaluates job postings for H-1B visa applicant friendliness
"""
import os
import time
import logging
from typing import Dict, Optional, List
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """Gemini-powered job analyzer for H-1B visa compatibility"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini API client
        
        Args:
            api_key: Gemini API key (defaults to env var)
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # Analysis prompt template
        self.prompt_template = """你是一个资深移民律师和技术招聘官。请分析以下岗位描述，评估其对 H-1B 签证申请人的友好程度。

评估维度：
1. H-1B 签证支持：是否明确提供 H-1B 签证赞助（Sponsorship）
2. 公司规模：是否是有 H-1B 赞助历史的大厂或知名公司
3. 职位要求：是否符合 H-1B 的专业性要求（本科及以上，专业对口）
4. 岗位稳定性：是否是长期正式职位（非合同工、非外包）
5. 抽签概率：公司是否有大量 H-1B 名额或历史中签率高

岗位信息：
职位名称：{title}
公司：{company}
地点：{location}
描述：
{description}

请按以下格式输出（必须严格遵守格式）：
评分：[1-10的数字]
推荐理由：[2-3句话的中文摘要，说明为什么推荐或不推荐此 H-1B 职位]
"""
    
    def analyze_job(
        self,
        title: str,
        company: str,
        location: str,
        description: str
    ) -> Dict[str, any]:
        """
        Analyze a single job posting
        
        Args:
            title: Job title
            company: Company name
            location: Job location
            description: Job description
            
        Returns:
            Dict with score (1-10), summary, and raw response
        """
        try:
            # Handle missing or short descriptions
            if not description or len(description.strip()) < 50:
                return {
                    "score": 0,
                    "summary": "职位描述信息不足，无法进行评估",
                    "raw_response": None,
                    "error": "Insufficient description"
                }
            
            # Format prompt
            prompt = self.prompt_template.format(
                title=title,
                company=company,
                location=location,
                description=description[:3000]  # Limit length to avoid token limits
            )
            
            # Call Gemini API
            response = self.model.generate_content(prompt)
            
            if not response or not response.text:
                return {
                    "score": 0,
                    "summary": "AI 分析失败",
                    "raw_response": None,
                    "error": "Empty response"
                }
            
            # Parse response
            result = self._parse_response(response.text)
            result["raw_response"] = response.text
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Analysis error for {title} at {company}: {e}")
            return {
                "score": 0,
                "summary": f"分析出错：{str(e)[:100]}",
                "raw_response": None,
                "error": str(e)
            }
    
    def _parse_response(self, response_text: str) -> Dict[str, any]:
        """
        Parse Gemini response into structured format
        
        Args:
            response_text: Raw response from Gemini
            
        Returns:
            Dict with score and summary
        """
        try:
            lines = response_text.strip().split('\n')
            score = 0
            summary = ""
            
            for line in lines:
                line = line.strip()
                
                # Extract score
                if line.startswith("评分：") or line.startswith("评分:"):
                    score_str = line.split("：")[-1].split(":")[-1].strip()
                    # Extract first number found
                    import re
                    numbers = re.findall(r'\d+', score_str)
                    if numbers:
                        score = int(numbers[0])
                        score = max(1, min(10, score))  # Clamp to 1-10
                
                # Extract summary
                elif line.startswith("推荐理由：") or line.startswith("推荐理由:"):
                    summary = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif summary and line and not line.startswith("评分"):
                    # Continue multi-line summary
                    summary += " " + line
            
            # Fallback if parsing failed
            if score == 0 or not summary:
                summary = response_text[:200] if not summary else summary
                
                # Try to extract any number as score
                import re
                numbers = re.findall(r'\d+', response_text)
                if numbers:
                    score = int(numbers[0])
                    score = max(1, min(10, score))
                else:
                    score = 5  # Default middle score
            
            return {
                "score": score,
                "summary": summary.strip()
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Response parsing error: {e}")
            return {
                "score": 5,
                "summary": response_text[:200]  # Return first 200 chars as fallback
            }
    
    def analyze_batch(
        self,
        jobs: List[Dict[str, str]],
        delay_between_calls: float = 1.0
    ) -> List[Dict[str, any]]:
        """
        Analyze multiple jobs with rate limiting
        
        Args:
            jobs: List of job dicts with title, company, location, description
            delay_between_calls: Seconds to wait between API calls
            
        Returns:
            List of analysis results
        """
        results = []
        
        for i, job in enumerate(jobs, 1):
            logger.info(f"🤖 Analyzing {i}/{len(jobs)}: {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}")
            
            result = self.analyze_job(
                title=job.get('title', 'Unknown'),
                company=job.get('company', 'Unknown'),
                location=job.get('location', 'Unknown'),
                description=job.get('description', '')
            )
            
            result['job_data'] = job
            results.append(result)
            
            # Rate limiting
            if i < len(jobs):
                time.sleep(delay_between_calls)
        
        return results
    
    def filter_by_score(
        self,
        analyzed_jobs: List[Dict],
        min_score: int = 6
    ) -> List[Dict]:
        """
        Filter jobs by minimum score threshold
        
        Args:
            analyzed_jobs: List of analyzed job dicts
            min_score: Minimum score to pass (1-10)
            
        Returns:
            Filtered list of high-scoring jobs
        """
        filtered = [
            job for job in analyzed_jobs
            if job.get('score', 0) >= min_score
        ]
        
        # Sort by score descending
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        logger.info(f"✅ {len(filtered)}/{len(analyzed_jobs)} jobs passed threshold (score >= {min_score})")
        
        return filtered


def main():
    """Test the analyzer"""
    analyzer = AIAnalyzer()
    
    # Test job
    test_job = {
        "title": "Senior Machine Learning Engineer",
        "company": "Google",
        "location": "Mountain View, CA",
        "description": """
        We are seeking an exceptional Senior ML Engineer to join our AI Research team.
        
        Responsibilities:
        - Design and implement novel deep learning architectures
        - Publish research papers at top-tier conferences (NeurIPS, ICML)
        - Lead cross-functional teams on cutting-edge AI projects
        
        Requirements:
        - PhD in Computer Science or related field
        - 5+ years of ML experience
        - Strong publication record
        
        We offer H-1B visa sponsorship and have a strong track record of successful petitions.
        """
    }
    
    result = analyzer.analyze_job(
        title=test_job["title"],
        company=test_job["company"],
        location=test_job["location"],
        description=test_job["description"]
    )
    
    logger.info("📊 Analysis Result:")
    logger.info(f"Score: {result['score']}/10")
    logger.info(f"Summary: {result['summary']}")
    logger.info(f"Raw Response: {result['raw_response']}")


if __name__ == "__main__":
    main()
