#!/bin/bash
# scripts/run_backend_tests.sh
# Standard shortcut to run the backend test suite locally with coverage

echo "=============================================="
echo "   Running QuDrugForge Backend Pytest Suite"
echo "=============================================="

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "Error: pytest is not installed in the current environment."
    echo "Please activate your virtual environment first."
    exit 1
fi

# Run the suite
pytest -v

echo "=============================================="
echo "Tests execution complete."
echo "=============================================="
