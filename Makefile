.PHONY: all install test lint format serve demo \
        docker-build docker-run clean help

# ─── Configuration ────────────────────────────────────────────────────────────
PYTHON      ?= python
PORT        ?= 8585
IMAGE_NAME  ?= flowlens
CONTAINER_NAME ?= flowlens-server

# ─── Default target ───────────────────────────────────────────────────────────
all: lint test

help:
	@echo "FlowLens — available make targets:"
	@echo ""
	@echo "  install       Install package with dev dependencies"
	@echo "  test          Run the full test suite"
	@echo "  lint          Run ruff + black check + mypy"
	@echo "  format        Auto-format with black and ruff --fix"
	@echo "  serve         Start the FlowLens API server (port $(PORT))"
	@echo "  demo          Run the demo agent"
	@echo "  docker-build  Build the Docker image"
	@echo "  docker-run    Run the server in Docker"
	@echo "  clean         Remove build artefacts and caches"
	@echo "  all           Run lint then test (default)"

# ─── Development setup ────────────────────────────────────────────────────────
install:
	$(PYTHON) -m pip install --upgrade pip
	pip install -e ".[dev]"
	pip install ruff black mypy pytest-cov

# ─── Testing ──────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --tb=short --cov=flowlens --cov-report=term-missing --cov-report=html
	@echo "Coverage HTML report: htmlcov/index.html"

# ─── Code quality ─────────────────────────────────────────────────────────────
lint:
	ruff check flowlens/ tests/
	black --check flowlens/ tests/ examples/
	mypy flowlens/ --ignore-missing-imports

format:
	black flowlens/ tests/ examples/
	ruff check --fix flowlens/ tests/

# ─── Running locally ──────────────────────────────────────────────────────────
serve:
	$(PYTHON) -m uvicorn flowlens.server.app:create_app \
		--factory --host 0.0.0.0 --port $(PORT) --reload

demo:
	$(PYTHON) -m examples.demo_agent

# ─── Docker ───────────────────────────────────────────────────────────────────
docker-build:
	docker build --target runtime -t $(IMAGE_NAME):latest .

docker-run:
	docker run --rm \
		--name $(CONTAINER_NAME) \
		-p $(PORT):$(PORT) \
		-v flowlens-data:/data \
		$(IMAGE_NAME):latest

docker-compose-up:
	docker compose up --build -d

docker-compose-down:
	docker compose down

# ─── Cleanup ──────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name build -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "coverage.xml" -delete 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	@echo "Clean complete."
