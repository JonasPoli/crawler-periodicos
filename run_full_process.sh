#!/bin/bash

echo "=========================================="
echo "      Jornal Crawler - Full Process       "
echo "=========================================="

# 1. Populate Database
echo ""
echo "[1/3] Syncing journals to database..."
python3 populate_db.py

# 2. Run Crawler
echo ""
echo "[2/3] Starting Crawler..."
echo "Note: This process may take a long time."
echo "You can stop it with Ctrl+C at any time and resume later."
echo "Progress is saved to the database."
python3 -u orchestrator.py

# 3. Run Processor (in case Step 2 was interrupted or to re-process)
echo ""
echo "[3/3] Running Data Extraction (PDFs -> CSV)..."
python3 -u processor.py

echo ""
echo "=========================================="
echo "              Done!                       "
echo "Check 'emails.csv' for results."
echo "=========================================="
