#!/bin/bash
# Quick setup script for Job Hunter Sentinel

set -e

echo "🎯 Job Hunter Sentinel - Setup Script"
echo "======================================"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed."
    echo "📦 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo "✅ uv found: $(uv --version)"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    uv venv .venv
else
    echo "✅ Virtual environment already exists"
fi

# Install dependencies
echo "📥 Installing dependencies..."
uv pip install -e .

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found"
    if [ -f ".env.example" ]; then
        echo "📋 Copying .env.example to .env..."
        cp .env.example .env
        echo "✏️  Please edit .env and add your API keys"
    fi
else
    echo "✅ .env file exists"
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "  source .venv/bin/activate"
echo ""
echo "Then you can run:"
echo "  python main.py"
