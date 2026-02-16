.PHONY: dev dev-backend dev-frontend dev-worker test-backend docker-up

dev:
	@echo "Run in separate terminals: make dev-backend, make dev-frontend, and optionally make dev-worker"

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

dev-worker:
	cd backend && rq worker default --url redis://localhost:6379/0

test-backend:
	cd backend && pytest

docker-up:
	docker compose up --build
