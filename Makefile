.PHONY: dev dev-backend dev-frontend test-backend docker-up

dev:
	@echo "Run backend and frontend in separate terminals: make dev-backend and make dev-frontend"

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

test-backend:
	cd backend && pytest

docker-up:
	docker compose up --build
