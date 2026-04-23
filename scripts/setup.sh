#!/bin/bash
# ============================================================
# Autonomous Content Bridge — One-Click Setup Script
# Run: bash scripts/setup.sh
# ============================================================
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_DIR="/opt/content-bridge"

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║     Autonomous Content Bridge — Setup            ║"
echo "║     Hermes Agent Creative Hackathon              ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Create data directories ─────────────────────
echo -e "${GREEN}[1/5]${NC} Creating data directories..."
mkdir -p "$PROJECT_DIR/data"/{downloads,processed,subtitles,logs}

# ── Step 2: Python virtual environment ──────────────────
echo -e "${GREEN}[2/5]${NC} Setting up Python virtual environment..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
    echo "  Created new virtualenv"
else
    echo "  Virtualenv already exists"
fi

source "$PROJECT_DIR/venv/bin/activate"

# ── Step 3: Install Python dependencies ─────────────────
echo -e "${GREEN}[3/5]${NC} Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# ── Step 4: Setup .env file ─────────────────────────────
echo -e "${GREEN}[4/5]${NC} Setting up environment..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  Created .env from .env.example"
    echo -e "  ${BOLD}⚠  IMPORTANT: Edit /opt/content-bridge/.env and add your API keys!${NC}"
else
    echo "  .env already exists"
fi

# ── Step 5: Test imports ────────────────────────────────
echo -e "${GREEN}[5/5]${NC} Testing Python imports..."
cd "$PROJECT_DIR"
python3 -c "
from backend.config import get_settings
from backend.database import Base
from backend.models import Job, JobStatus
print('  ✔ All imports successful')
settings = get_settings()
print(f'  ✔ Config loaded: data_dir={settings.data_dir}')
"

echo ""
echo -e "${GREEN}${BOLD}✅ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys:"
echo "     nano /opt/content-bridge/.env"
echo ""
echo "  2. Start the backend:"
echo "     cd /opt/content-bridge"
echo "     source venv/bin/activate"
echo "     uvicorn backend.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "  3. Or use PM2:"
echo "     pm2 start ecosystem.config.js"
echo ""
