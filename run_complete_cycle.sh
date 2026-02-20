#!/bin/bash

# Configuration
PYTHON_CMD="python3"
WORKERS=4

echo "=================================================="
echo "   CRAWLER COMPLETE CYCLE ORCHESTRATOR"
echo "=================================================="
echo "Timestamp: $(date)"

# 1. Dependency Check
echo ""
echo "[1/4] Checking Dependencies..."
if ! $PYTHON_CMD -c "import pdfplumber" 2>/dev/null; then
    echo "WARNING: pdfplumber not found. Installing..."
    pip install pdfplumber
else
    echo "OK: pdfplumber is installed."
fi

# 2. Discovery Phase
# This populates the database with Journals, Editions, and Articles (found status)
echo ""
echo "[2/4] Running DISCOVERY Phase..."
echo "Scanning journals for new editions and articles..."
$PYTHON_CMD run_fast.py discover

if [ $? -ne 0 ]; then
    echo "ERROR: Discovery phase failed. Exiting."
    exit 1
fi
echo "Discovery phase complete."

# 3. Processing Phase (Super Mode)
# This runs Crawler (Download), Processor (Extract), and Verifier (Check Emails) in parallel.
# Since we increased the timeout in worker_processor.py, they should stay alive.
echo ""
echo "[3/4] Starting WORKERS (Download, Process, Verify)..."
echo "Launching workers in parallel. Press Ctrl+C to stop manually."
echo "Logs will be printed to stdout."

# We use the 'super' mode of run_fast.py which launches all worker types
$PYTHON_CMD run_fast.py super --workers $WORKERS

echo ""
echo "[4/4] Workflow finished."
echo "Timestamp: $(date)"
