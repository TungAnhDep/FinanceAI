
PYTHON = python
PIP = pip
UVICORN = uvicorn
MAIN_APP = main:app

.PHONY: help install dev lint clean

help:
	@echo "install : Install requirements.txt"
	@echo "dev     : Run FastAPI development server"
	@echo "lint    : Check code formatting and type annotations (Ruff & Mypy)"
	@echo "clean   : Remove Python cache files (__pycache__)"

# 1. Install dependencies
install:
	$(PIP) install -r requirements.txt
	$(PIP) install ruff mypy types-python-dotenv 

# 2. Run development server
dev:
	$(PYTHON) -m uvicorn $(MAIN_APP) --host 0.0.0.0 --port 8000 --reload

# 3. Run linters and type checkers
lint:
	@echo "--- Running Ruff (Linter) ---"
	ruff check .
	@echo "--- Running Mypy (Type Checker) ---"
	mypy . --ignore-missing-imports

# 4. Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleaned up pycache."