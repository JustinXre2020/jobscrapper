# 🎯 Job Hunter Sentinel

一个端到端的自动化职位抓取与推荐系统，专为 O-1 签证申请人设计。利用 AI 智能分析职位友好度，每日自动推送高匹配度岗位。

## ✨ 核心功能

- 🔍 **多源抓取**: 聚合 LinkedIn、Indeed、ZipRecruiter、Google Jobs
- 🤖 **AI 智能评分**: 使用 Gemini 1.5 Flash 分析职位对 O-1 签证的友好度
- 📧 **精美邮件推送**: 每日发送排版整齐的 HTML 职位精选
- 🗑️ **自动去重**: 基于 URL 的智能去重，避免重复推送
- 💾 **本地数据存储**: 所有抓取数据自动保存为 JSON/CSV 格式
- ⏰ **定时任务**: 每天 8点、12点、18点自动运行（支持本地 Cron 和 GitHub Actions）
- 🗂️ **自动清理**: 超过 7 天的数据自动删除
- ⏰ **定时任务**: GitHub Actions 每日自动运行
- 🛡️ **异常处理**: 429 速率限制自动退避，空结果友好通知

---

## 📋 环境要求

- **Python**: 3.10+
- **包管理器**: [uv](https://github.com/astral-sh/uv) (推荐) 或 pip
- **API Keys**: 
  - [Google AI Studio](https://makersuite.google.com/app/apikey) (Gemini API)
  - [Resend](https://resend.com/api-keys) (邮件服务)

---

## 🚀 快速开始

### 方法 1: 一键安装脚本 (推荐)

```bash
cd apps/jobsrapper
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
cd apps/jobsrapper

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
# API Keys
GEMINI_API_KEY=your_gemini_api_key_here
RESEND_API_KEY=your_resend_api_key_here
RECIPIENT_EMAIL=your_email@example.com

# 数据库配置（本地测试用 SQLite）
DATABASE_URL=sqlite:///./jobs.db

# 搜索配置
SEARCH_TERMS=software engineer,senior software engineer,machine learning engineer
LOCATIONS=San Francisco CA,New York NY,Seattle WA
RESULTS_WANTED=20
HOURS_OLD=24
MIN_SCORE=6
```

### 4. 运行测试

```bash
# 确保虚拟环境已激活
source .venv/bin/activate

# 测试各模块

```bash
# 测试各模块
python scraper.py        # 测试职位抓取
python ai_analyzer.py    # 测试 AI 分析
python database.py       # 测试数据库
python email_sender.py   # 测试邮件发送
python data_manager.py   # 测试数据管理

# 运行完整流程
python main.py
```

### 5. 设置定时任务（可选）

```bash
# 安装本地 cron 定时任务（每天 8点、12点、18点运行）
./install_cron.sh

# 查看已安装的任务
crontab -l

# 卸载定时任务
./uninstall_cron.sh
```

---

## 📁 项目结构

```
jobsrapper/
├── main.py              # 主程序入口
├── scraper.py           # 职位抓取引擎
├── ai_analyzer.py       # Gemini AI 分析器
├── database.py          # 去重与持久化
├── email_sender.py      # 邮件发送模块
├── data_manager.py      # 数据存储管理 (NEW)
├── scraper.py           # 职位抓取引擎
├── ai_analyzer.py       # Gemini AI 分析器
├── database.py          # 去重与持久化
├── email_sender.py      # 邮件发送模块
├── pyproject.toml       # 项目配置和依赖管理 (uv)
├── requirements.txt     # 传统依赖列表 (向后兼容)
├── requirements.lock    # 锁定的依赖版本
├── .venv/               # 虚拟环境目录 (git 忽略)
├── .env.example         # 环境变量模板
├── .gitignore           # Git 忽略规则
└── README.md            # 本文档
```

---

## ⚙️ 配置说明

### 环境变量详解

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `GEMINI_API_KEY` | Google AI Studio 密钥 | `AIza...` |
| `RESEND_API_KEY` | Resend 邮件服务密钥 | `re_...` |
| `RECIPIENT_EMAIL` | 接收通知的邮箱 | `you@example.com` |
| `DATABASE_URL` | 数据库连接（SQLite/Supabase） | `sqlite:///./jobs.db` |
| `SEARCH_TERMS` | 职位关键词（逗号分隔） | `software engineer,ml engineer` |
| `LOCATIONS` | 搜索地点（逗号分隔） | `San Francisco CA,NYC` |
| `RESULTS_WANTED` | 每个搜索返回结果数 | `20` |
| `HOURS_OLD` | 职位时间窗口（小时） | `24` |
| `MIN_SCORE` | 最低推荐分数（1-10） | `6` |

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

## 🤖 GitHub Actions 自动化

### 配置步骤

1. **添加 Secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `GEMINI_API_KEY`
   - `RESEND_API_KEY`
   - `RECIPIENT_EMAIL`
   - `DATABASE_URL` (可选)

2. **添加 Variables** (Settings → Secrets and variables → Actions → Variables):
   - `SEARCH_TERMS` (默认: `software engineer`)
   - `LOCATIONS` (默认: `San Francisco, CA`)
   - `RESULTS_WANTED` (默认: `20`)
   - `HOURS_OLD` (默认: `24`)
   - `MIN_SCORE` (默认: `6`)

3. **启用 Workflow**:
   - 进入 Actions 标签页
   - 找到 "Job Hunter Sentinel Daily Run"
   - 点击 "Enable workflow"

### 运行时间

默认每天 **UTC 13:00** 运行 (北京时间晚上 9 点 / 美东早上 6 点)

可在 `.github/workflows/job_hunter.yml` 中修改 `cron` 表达式：

```yaml
schedule:
  - cron: '0 13 * * *'  # 分 时 日 月 星期
```

### 手动触发

在 Actions 页面点击 "Run workflow" 按钮即可立即执行。

---

## 📊 工作流程

```
┌─────────────────┐
│  1. 抓取职位    │  → 多源聚合 (LinkedIn, Indeed, etc.)
└────────┬────────┘
         ↓
┌─────────────────┐
│  2. AI 分析     │  → Gemini 评估 O-1 签证友好度 (1-10分)
└────────┬────────┘
         ↓
┌─────────────────┐
│  3. 分数过滤    │  → 保留高分职位 (>= MIN_SCORE)
└────────┬────────┘
         ↓
┌─────────────────┐
│  4. 去重检查    │  → 数据库查询，过滤已发送职位
└────────┬────────┘
         ↓
┌─────────────────┐
│  5. 邮件推送    │  → 精美 HTML 格式邮件
└────────┬────────┘
         ↓
┌─────────────────┐
│  6. 标记已发送  │  → 写入数据库，防止重复
└─────────────────┘
```

---

## 🎨 邮件样式

邮件采用现代化设计，包含：

- 🎯 渐变色标题
- 📊 职位数量统计
- ⭐ 分数色彩编码 (8+ 绿色强推, 6-7 蓝色推荐)
- 💡 AI 推荐理由高亮
- 🔗 一键直达申请链接

---

## 🛠️ 异常处理

### 429 速率限制

自动实现指数退避 (Exponential Backoff):
- 第 1 次重试: 等待 2 秒
- 第 2 次重试: 等待 4 秒
- 第 3 次重试: 等待 8 秒

### 空结果处理

当无符合条件的职位时，发送友好的"今日无新职位"通知，避免误以为系统失效。

### 数据库降级

如果 SQLite/Supabase 连接失败，自动降级到本地文本文件 (`sent_jobs.txt`)。

---

## 📈 性能与成本

- **抓取速度**: 约 5-10 秒/查询 (含礼貌性延迟)
- **AI 分析**: 约 1-2 秒/职位 (Gemini 1.5 Flash)
- **邮件发送**: < 1 秒
- **总耗时**: 典型运行 2-5 分钟 (20 个职位)
- **API 成本**: 
  - Gemini: 免费额度充足 (60 requests/min)
  - Resend: 免费 100 封/天

---

## 🔧 高级配置

### 使用 Supabase 数据库

```env
DATABASE_URL=postgresql://user:pass@host.supabase.co:5432/postgres
```

### 调整 AI 评分标准

编辑 `ai_analyzer.py` 中的 `prompt_template`，自定义评估维度。

### 修改邮件模板

编辑 `email_sender.py` 中的 `create_email_body()` 和 `create_job_html()` 方法。

### 添加更多职位源

在 `scraper.py` 的 `self.sites` 中添加支持的站点（需 python-jobspy 支持）。

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

- [python-jobspy](https://github.com/Bunsly/JobSpy) - 职位抓取库
- [Google Gemini](https://ai.google.dev/) - AI 分析引擎
- [Resend](https://resend.com/) - 邮件推送服务

---

## 📞 支持

遇到问题？请创建 [Issue](https://github.com/srbhr/Resume-Matcher/issues) 或参考主项目文档。

---

**Happy Job Hunting! 🎉**
