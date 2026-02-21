# 🎯 Job Hunter Sentinel

一个端到端的自动化职位抓取与推荐系统，适用于求职场景。系统会抓取职位、去重、LLM 筛选并按收件人发送职位摘要邮件。

## ✨ 核心功能

- 🔍 **多源抓取**: 聚合 LinkedIn、Indeed、ZipRecruiter、Google Jobs
- 🤖 **LLM 智能筛选**: 基于 LangGraph + OpenRouter 的结构化评估流程
- 📧 **邮件推送**: 每日发送 HTML 职位摘要（标题/公司/地点/链接，**不包含职位描述正文**）
- 🗑️ **增强去重**: 先按 `job_url` 去重，再按 `title + company` 合并重复岗位并合并地点
- 💾 **本地数据存储**: 抓取数据自动保存为 JSON/CSV，已发送记录保存在数据库
- 🪵 **统一日志**: 全项目使用 Loguru，文件与控制台日志格式统一
- ⏰ **自动调度**: 支持本地执行与 GitHub Actions 定时运行（每日两次）
- 🛡️ **异常处理**: 429 速率限制自动退避，空结果会发送友好通知

---

## 📋 环境要求

- **Python**: 3.13+
- **包管理器**: [uv](https://github.com/astral-sh/uv) (推荐) 或 pip
- **必要配置**:
  - `OPENROUTER_API_KEY`
  - `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD`

---

## 🚀 快速开始

### 方法 1: 一键安装脚本 (推荐)

```bash
cd jobscrapper
./setup.sh
```

这个脚本会自动：
- 安装 uv (如果未安装)
- 创建虚拟环境
- 安装所有依赖
- 复制 `.env.example` 到 `.env` (如果不存在)

### 方法 2: 手动安装

#### 1. 安装 uv (如果尚未安装)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或使用 pip
pip install uv
```

#### 2. 安装依赖

```bash
cd jobscrapper

# 使用 uv 创建虚拟环境并安装依赖
uv venv .venv
uv pip install -e .

# 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate  # Windows
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

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

### 4. 运行测试

```bash
# 测试模块
python scraper.py

# 运行完整流程
python main.py

# 代码质量
ruff check .
black --check .

# 测试
pytest tests/
```

---

## 📁 项目结构

```text
jobscrapper/
├── main.py                    # 主入口
├── scraper.py                 # 抓取引擎（含增强去重逻辑）
├── collect_jobs.py            # 批量抓取脚本
├── config.py                  # 配置解析
├── filtering/                 # 过滤工作流入口
├── agent/                     # LangGraph 节点与图
├── infra/
│   ├── llm_client.py          # OpenRouter 客户端
│   └── logging_config.py      # Loguru 统一日志配置
├── notification/
│   └── email_sender.py        # 邮件模板与发送
├── storage/
│   ├── database.py            # 已发送岗位去重记录
│   └── data_manager.py        # JSON/CSV 数据管理
├── tests/
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## ⚙️ 配置说明

### 环境变量详解

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 密钥 | `sk-or-...` |
| `OPENROUTER_MODEL` | 模型标识 | `liquid/lfm-2.5-1.2b-instruct:free` |
| `GMAIL_EMAIL` | 发件邮箱 | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | Gmail App Password | `xxxx xxxx xxxx xxxx` |
| `RECIPIENTS` | 收件人 JSON 配置 | `[{"email":"a@b.com",...}]` |
| `SEARCH_TERMS` | 搜索关键词（逗号分隔） | `software engineer,data engineer` |
| `LOCATIONS` | 搜索地点（逗号分隔） | `San Francisco, CA,New York, NY` |
| `RESULTS_WANTED` | 每个查询返回数 | `20` |
| `HOURS_OLD` | 职位时间窗口（小时） | `24` |

--------|------|------|
| `SEARCH_TERMS` | 职位关键词（逗号分隔） | `software engineer,ml engineer` |
| `LOCATIONS` | 搜索地点（逗号分隔） | `San Francisco CA,NYC` |
| `RESULTS_WANTED` | 每个搜索返回结果数 | `20` |
| `HOURS_OLD` | 职位时间窗口（小时） | `24` |

---

## 🔧 依赖管理

本项目使用 [uv](https://github.com/astral-sh/uv) 进行依赖管理，提供以下优势：

- ⚡ **极速安装**: 比 pip 快 10-100 倍
- 🔒 **精确锁定**: 通过 `requirements.lock` 确保可重现构建
- 🌐 **兼容性**: 完全兼容 pip 和 PyPI
- 💾 **缓存优化**: 智能缓存减少网络请求

### uv 常用命令

```bash
# 创建虚拟环境
uv venv .venv

# 安装依赖
uv pip install -e .

# 添加新依赖
uv pip install package-name

# 更新所有依赖
uv pip install -e . --upgrade

# 查看已安装包
uv pip list

# 生成锁定文件
uv pip freeze > requirements.lock
```

### 传统 pip 方式

如果不想使用 uv，仍可使用传统 pip：

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

---

## 📊 工作流程

```text
1) 抓取职位（多站点）
2) 抓取结果去重（job_url + title/company，合并 location）
3) 过滤历史已发送岗位
4) LLM 结构化评估筛选
5) 按收件人规则生成邮件并发送
6) 标记已发送并清理过期数据
```

---

## 🎨 邮件样式

邮件模板包含：

- 🎯 渐变色标题
- 📊 职位数量统计
- 🏢 公司 + 📍地点
- 🟢/🔴 签证信息徽章
- 🔗 一键查看详情链接

> 说明：邮件中不再包含职位描述正文。

---

## 🛠️ 异常处理

### 429 速率限制

自动实现指数退避 (Exponential Backoff):
- 第 1 次重试: 等待 2 秒
- 第 2 次重试: 等待 4 秒
- 第 3 次重试: 等待 8 秒

### 空结果处理

当无符合条件的职位时，发送友好的"今日无新职位"通知，避免误以为系统失效。

---

## 🔧 高级配置

### 调整 Agent 过滤逻辑

- 过滤入口：`filtering/job_filter.py`
- Agent 节点与图：`agent/`
- Prompt：`agent/prompts/`

### 修改邮件模板

编辑 `notification/email_sender.py` 中的 `create_email_body()` 与 `create_job_html()`。

### 添加更多职位源

在 `scraper.py` 的 `self.sites` 中添加站点（需 `python-jobspy` 支持）。

---

## 📝 验收标准

- [x] 成功抓取职位 (控制台显示 `Found X jobs`)
- [x] AI 解析生成中文摘要和合理评分
- [x] 去重功能有效 (连续运行不发送重复邮件)
- [x] 邮件到达收件箱，排版整齐
- [x] 429 错误自动重试
- [x] 空结果发送友好通知

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](../../LICENSE) 文件

---

## 🙏 致谢

- [python-jobspy](https://github.com/Bunsly/JobSpy)
- [OpenRouter](https://openrouter.ai/)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Loguru](https://github.com/Delgan/loguru)

---

## 📞 支持

遇到问题？请创建 [Issue](https://github.com/srbhr/Resume-Matcher/issues) 或参考主项目文档。

---

**Happy Job Hunting! 🎉**
