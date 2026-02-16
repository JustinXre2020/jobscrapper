#!/bin/bash
# Quick reference for Job Hunter Sentinel commands

╔═══════════════════════════════════════════════════════════════╗
║         Job Hunter Sentinel - 快速命令参考                     ║
╚═══════════════════════════════════════════════════════════════╝

📦 安装 & 配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
./setup.sh                    # 一键安装所有依赖
cp .env.example .env          # 复制环境变量模板
nano .env                     # 编辑 API keys

🚀 运行程序
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
source .venv/bin/activate     # 激活虚拟环境
python main.py                # 运行完整流程

🧪 测试模块
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
python scraper.py             # 测试职位抓取
python ai_analyzer.py         # 测试 AI 分析
python database.py            # 测试数据库
python email_sender.py        # 测试邮件发送
python data_manager.py        # 测试数据管理


📊 查看日志
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tail -f logs/cron_08.log      # 查看 8点运行日志
tail -f logs/cron_12.log      # 查看 12点运行日志
tail -f logs/cron_18.log      # 查看 18点运行日志

💾 数据管理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ls -lh data/                  # 查看保存的数据文件
python data_manager.py        # 查看数据统计
cat data/jobs_*.json | jq     # 查看 JSON 数据（需要 jq）

📁 数据位置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
data/jobs_*.json              # JSON 格式（完整数据）
data/jobs_*.csv               # CSV 格式（便于分析）
logs/cron_*.log               # 运行日志

🔧 维护命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
uv pip install -e . --upgrade # 更新所有依赖
rm -rf data/*.json            # 清空数据文件
rm -rf logs/*.log             # 清空日志文件

📚 查看文档
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cat README.md                 # 完整文档
cat DATA_STORAGE.md           # 数据存储说明
cat QUICKSTART.md             # 快速开始指南
cat MIGRATION.md              # uv 迁移说明

💡 提示：所有脚本都需要在虚拟环境激活后运行！
   source .venv/bin/activate

