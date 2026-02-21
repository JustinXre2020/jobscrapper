# 🎯 Job Hunter Sentinel

An end-to-end automated job scraping and recommendation system. It collects jobs from multiple boards, deduplicates them, filters them with an LLM workflow, and sends curated email digests to recipients.

## ✨ Core Features

- 🔍 **Multi-source scraping**: Aggregates jobs from LinkedIn, Indeed, ZipRecruiter, and Google Jobs
- 🤖 **LLM-based filtering**: Uses LangGraph + OpenRouter for structured evaluation
- 📧 **Email delivery**: Sends daily HTML digests (title/company/location/link, **no full job description body**)
- 🗑️ **Enhanced deduplication**: Deduplicates by `job_url`, then merges duplicates by `title + company` and combines locations
- 💾 **Local data storage**: Saves scraped results as JSON/CSV and stores sent-job records in the database
- 🪵 **Unified logging**: Uses Loguru with consistent console/file output
- ⏰ **Scheduled automation**: Supports local runs and scheduled GitHub Actions runs (daily at 1:00 PM EST)
- 🛡️ **Error handling**: Retries with backoff on 429 rate limits and sends friendly empty-result notifications

---

## 📋 Requirements

- **Python**: 3.13+
- **Package manager**: [uv](https://github.com/astral-sh/uv) (recommended) or pip
- **Required configuration**:
  - `OPENROUTER_API_KEY`
  - `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD`

---

## 🚀 Quick Start

### Method 1: One-step setup script (Recommended)

```bash
cd jobscrapper
./setup.sh
```

This script automatically:
- Installs uv (if missing)
- Creates a virtual environment
- Installs dependencies
- Copies `.env.example` to `.env` (if missing)

### Method 2: Manual setup

#### 1) Install uv (if needed)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# or with pip
pip install uv
```

#### 2) Install dependencies

```bash
cd jobscrapper

# Create venv and install project in editable mode
uv venv .venv
uv pip install -e .

# Activate virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

#### 3) Configure environment variables

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Email
GMAIL_EMAIL=your_email@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
RECIPIENTS=[{"email":"you@example.com","needs_sponsorship":true,"search_terms":["software engineer"]}]

# LLM
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=liquid/lfm-2.5-1.2b-instruct:free

# Scraping
SEARCH_TERMS=software engineer,data engineer
LOCATIONS=San Francisco, CA,New York, NY
RESULTS_WANTED=20
HOURS_OLD=24
```

#### 4) Run checks and the pipeline

```bash
# Run full pipeline
python src/main.py

# Code quality
ruff check .
black --check .

# Tests (set src as source root in CLI environments)
PYTHONPATH=src pytest tests/
```

---

## 📁 Project Structure

```text
jobscrapper/
├── src/
│   ├── main.py                # Main entry point
│   ├── utils/config.py        # Configuration parsing
│   ├── infra/
│   │   ├── scraper.py         # Scraper engine (python-jobspy)
│   │   ├── llm_client.py      # OpenRouter client
│   │   └── logging_config.py  # Unified Loguru logging
│   ├── filtering/             # Filtering workflow entry
│   ├── agent/                 # LangGraph nodes and graph
│   ├── notification/
│   │   └── email_sender.py    # Email template + delivery
│   └── storage/
│       ├── database.py        # Sent-job deduplication records
│       └── data_manager.py    # JSON/CSV data management
├── tests/
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | `sk-or-...` |
| `OPENROUTER_MODEL` | Model identifier | `liquid/lfm-2.5-1.2b-instruct:free` |
| `GMAIL_EMAIL` | Sender email | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | Gmail App Password | `xxxx xxxx xxxx xxxx` |
| `RECIPIENTS` | Recipient JSON config | `[{"email":"a@b.com",...}]` |
| `SEARCH_TERMS` | Search keywords (comma-separated) | `software engineer,data engineer` |
| `LOCATIONS` | Search locations (comma-separated) | `San Francisco, CA,New York, NY` |
| `RESULTS_WANTED` | Results per query | `20` |
| `HOURS_OLD` | Job age window (hours) | `24` |

---

## 📊 Pipeline Flow

```text
1) Scrape jobs from multiple sites
2) Deduplicate scraped jobs (job_url + title/company merge)
3) Filter out already-sent jobs
4) Run LLM-based structured filtering
5) Build per-recipient email digest and send
6) Mark sent jobs and clean old data
```

---

## 🔧 Advanced Configuration

### Adjust agent filtering logic

- Filtering entry: `src/filtering/job_filter.py`
- Agent nodes and graph: `src/agent/`
- Prompts: `src/agent/prompts/`

### Modify email templates

Edit `src/notification/email_sender.py` (`create_email_body()` and `create_job_html()`).

### Add more scraping sources

Update `self.sites` in `src/infra/scraper.py` (must be supported by `python-jobspy`).

---

## 📝 Acceptance Checklist

- [x] Jobs are scraped successfully (`Found X jobs` in logs)
- [x] LLM analysis produces structured and reasonable evaluation output
- [x] Deduplication prevents duplicate emails across repeated runs
- [x] Emails are delivered with clean formatting
- [x] 429 retries work automatically
- [x] Empty-result notifications are sent correctly

---

## 🤝 Contributing

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push your branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under MIT. See [LICENSE](LICENSE).

---

## 🙏 Acknowledgements

- [python-jobspy](https://github.com/Bunsly/JobSpy)
- [OpenRouter](https://openrouter.ai/)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Loguru](https://github.com/Delgan/loguru)

---

## 📞 Support

If you run into issues, open an issue in this repository and include logs/config details (with secrets removed).

---

**Happy Job Hunting! 🎉**
