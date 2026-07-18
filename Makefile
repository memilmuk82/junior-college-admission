PYTHON := uv run
TEST_DATABASE_URL := postgresql+psycopg://admission_test:test-only-password@127.0.0.1:$${TEST_POSTGRES_PORT:-55432}/admission_test
COMPOSE_TEST_ENV := SECRET_KEY=test-only-secret DATABASE_URL=$(TEST_DATABASE_URL) POSTGRES_PASSWORD=test-only-password
ALPHA_ENV_FILE ?= .env.alpha
ALPHA_WEB_PORT ?= 5001
BETA_ENV_FILE ?= .env.beta
BETA_WEB_PORT ?= 5002
PRODUCTION_ENV_FILE ?= .env.production
PRODUCTION_URL ?=
PRODUCTION_CA_CERT ?=
PRODUCTION_BACKUP_DIR ?= backups/production
BACKUP_FILE ?=
ROLLBACK_APP_IMAGE ?=
ROLLBACK_APP_IMAGE_ID ?=
ROLLBACK_DATABASE_RESTORE_CONFIRMED ?=
OIDC_CHANGE_APPROVED ?=
OIDC_HOST_GATE_CONFIRMED ?=
OIDC_BACKUP_RESTORE_CONFIRMED ?=

.PHONY: setup test-unit test-integration test-e2e test-phase13-e2e lint validate-rules check-sensitive-data check production-bootstrap production-preflight production-up production-check production-e2e production-status production-logs production-down production-origin-up production-origin-check production-origin-status production-origin-logs production-origin-down production-origin-oidc-up production-origin-oidc-check production-origin-oidc-status production-origin-oidc-disable production-origin-rollback-app production-origin-backup production-origin-backup-verify production-origin-restore-verify production-origin-metrics alpha-up alpha-check alpha-e2e alpha-e2e-full alpha-status alpha-logs alpha-down beta-up beta-check beta-e2e beta-e2e-full beta-status beta-logs beta-down

setup:
	uv sync --frozen
	npm ci

test-unit:
	$(PYTHON) pytest tests/test_admin_auth.py tests/test_authentication.py tests/test_admission_results.py tests/test_ai_http_providers.py tests/test_ai_payloads.py tests/test_ai_security.py tests/test_rule_admin.py tests/test_score_rule_csv_preview.py tests/test_app.py tests/test_application_policies.py tests/test_consultation_forms.py tests/test_phase13_multi_program.py tests/test_eligibility.py tests/test_google_oidc_operations.py tests/test_host_nginx_security.py tests/test_image_imports.py tests/test_pilot_candidates.py tests/test_pilot_golden_candidates.py tests/test_postgres_operations.py tests/test_production_bootstrap.py tests/test_production_config.py tests/test_production_https_operations.py tests/test_review_forms.py tests/test_review_state.py tests/test_scanned_pdf_imports.py tests/test_score_calculation.py tests/test_score_components.py tests/test_score_conversion.py tests/test_score_golden.py tests/test_score_inputs.py tests/test_score_properties.py tests/test_score_rule_schema.py tests/test_score_selection.py tests/test_structured_imports.py tests/test_temporary_uploads.py tests/test_text_pdf_imports.py tests/test_validate_rules.py

test-integration:
	$(COMPOSE_TEST_ENV) docker compose --profile test rm -f -s -v db-test
	$(COMPOSE_TEST_ENV) docker compose --profile test up -d --wait db-test
	@status=0; TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTHON) pytest tests/test_admin_rule_routes.py tests/test_auth_routes.py tests/test_membership.py tests/test_score_rule_csv_drafts.py tests/test_admission_result_models.py tests/test_ai_credentials.py tests/test_ai_routes.py tests/test_rule_admin_models.py tests/test_confirmed_imports.py tests/test_consultations.py tests/test_consultation_routes.py tests/test_phase13_batch_postgres.py tests/test_database.py tests/test_migrations.py tests/test_models.py tests/test_published_rules.py tests/test_review_routes.py || status=$$?; \
		if [ $$status -eq 0 ]; then $(COMPOSE_TEST_ENV) COMPOSE_FILE=docker-compose.yml DB_SERVICE=db-test ./scripts/collect_postgres_metrics.sh > /dev/null || status=$$?; fi; \
		if [ $$status -eq 0 ]; then $(COMPOSE_TEST_ENV) COMPOSE_FILE=docker-compose.yml DB_SERVICE=db-test ./scripts/check_postgres_backup_restore.sh || status=$$?; fi; \
		$(COMPOSE_TEST_ENV) docker compose --profile test rm -f -s -v db-test; \
		exit $$status

test-e2e:
	npm run test:e2e

test-phase13-e2e:
	npx playwright test --config tests/playwright.phase13.config.js

lint:
	$(PYTHON) ruff check .
	$(PYTHON) ruff format --check .
	$(PYTHON) mypy app scripts tests

validate-rules:
	$(PYTHON) python -m scripts.validate_rules

check-sensitive-data:
	$(PYTHON) python scripts/check_sensitive_data.py

check: lint test-unit test-integration validate-rules check-sensitive-data

production-bootstrap:
	test -n "$(PRODUCTION_HOST)"
	UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.bootstrap_production --public-host "$(PRODUCTION_HOST)"

production-preflight:
	UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_readiness

production-up:
	test -f $(PRODUCTION_ENV_FILE)
	PRODUCTION_ENV_FILE=$(PRODUCTION_ENV_FILE) UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_readiness
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) up -d --build --wait

production-check:
	test -n "$(PRODUCTION_URL)" && test -n "$(PRODUCTION_CA_CERT)"
	PRODUCTION_URL="$(PRODUCTION_URL)" PRODUCTION_CA_CERT="$(PRODUCTION_CA_CERT)" UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_https
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) exec -T proxy-production nginx -t
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) exec -T web-production flask --app wsgi db current

production-e2e:
	@test -n "$(PRODUCTION_URL)" && test -n "$(PRODUCTION_ADMIN_USERNAME)" && test -n "$(PRODUCTION_ADMIN_PASSWORD)"
	@ADMIN_URL="$(PRODUCTION_URL)" ADMIN_USERNAME="$(PRODUCTION_ADMIN_USERNAME)" ADMIN_PASSWORD="$(PRODUCTION_ADMIN_PASSWORD)" E2E_IGNORE_HTTPS_ERRORS="$(E2E_IGNORE_HTTPS_ERRORS)" SCREENSHOT_DIR=/tmp npm run test:e2e -- e2e/admin.spec.js

production-status:
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) ps

production-logs:
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) logs --tail=200 proxy-production web-production db-production

production-down:
	docker compose -f docker-compose.production.yml --env-file $(PRODUCTION_ENV_FILE) stop proxy-production web-production db-production

production-origin-up:
	test -f $(PRODUCTION_ENV_FILE)
	PRODUCTION_ENV_FILE=$(PRODUCTION_ENV_FILE) UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_readiness
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) up -d --build --wait web-production

production-origin-check:
	test -n "$(PRODUCTION_URL)" && test -n "$(PRODUCTION_CA_CERT)"
	PRODUCTION_URL="$(PRODUCTION_URL)" PRODUCTION_CA_CERT="$(PRODUCTION_CA_CERT)" UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_https
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) exec -T web-production flask --app wsgi db current

production-origin-status:
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) ps

production-origin-logs:
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) logs --tail=200 web-production db-production

production-origin-down:
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) stop web-production db-production

# Google OIDC remains opt-in. Enabling it can deploy the current image and run
# migrations, so all three independent change-window attestations are required.
production-origin-oidc-up:
	test "$(OIDC_CHANGE_APPROVED)" = "APPROVED"
	test "$(OIDC_HOST_GATE_CONFIRMED)" = "PASSED"
	test "$(OIDC_BACKUP_RESTORE_CONFIRMED)" = "VERIFIED"
	test -f $(PRODUCTION_ENV_FILE)
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) config --quiet
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) build web-production
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) run --rm --no-deps web-production python -c 'from app import create_app; app = create_app(); assert app.config["APP_ENV"] == "production"; assert app.config["GOOGLE_OIDC_ENABLED"] is True'
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) up -d --no-build --wait web-production

production-origin-oidc-check:
	test -n "$(PRODUCTION_URL)" && test -n "$(PRODUCTION_CA_CERT)"
	PRODUCTION_URL="$(PRODUCTION_URL)" PRODUCTION_CA_CERT="$(PRODUCTION_CA_CERT)" UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_https
	PRODUCTION_URL="$(PRODUCTION_URL)" PRODUCTION_CA_CERT="$(PRODUCTION_CA_CERT)" UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_google_oidc_https
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) exec -T web-production flask --app wsgi db current

production-origin-oidc-status:
	docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml -f docker-compose.google-oidc.yml --env-file $(PRODUCTION_ENV_FILE) ps

# This is an OIDC emergency stop, not an application or database rollback. It
# forces the base profile's disabled value and removes the OIDC secret mounts.
production-origin-oidc-disable:
	test "$(OIDC_CHANGE_APPROVED)" = "APPROVED"
	test -f $(PRODUCTION_ENV_FILE)
	GOOGLE_OIDC_ENABLED=false PRODUCTION_ENV_FILE=$(PRODUCTION_ENV_FILE) UV_CACHE_DIR=/tmp/junior-college-admission-uv-cache $(PYTHON) python -m scripts.check_production_readiness
	GOOGLE_OIDC_ENABLED=false docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) up -d --no-build --no-deps --force-recreate --wait web-production

# Image-only rollback is forbidden after a schema change. This target is usable only
# after the approved pre-change DB backup has been restored and verified separately.
production-origin-rollback-app:
	test "$(ROLLBACK_DATABASE_RESTORE_CONFIRMED)" = "RESTORED_AND_VERIFIED"
	test -n "$(ROLLBACK_APP_IMAGE)"
	test -n "$(ROLLBACK_APP_IMAGE_ID)"
	COMPOSE_FILE=docker-compose.production.yml COMPOSE_OVERRIDE_FILE=docker-compose.host-nginx.yml COMPOSE_ENV_FILE="$(PRODUCTION_ENV_FILE)" DB_SERVICE=db-production METRICS_SQL=deploy/postgres_demo_rollback_gate.sql ./scripts/collect_postgres_metrics.sh > /dev/null
	@actual_id=$$(docker image inspect --format '{{.Id}}' "$(ROLLBACK_APP_IMAGE)"); \
		test "$$actual_id" = "$(ROLLBACK_APP_IMAGE_ID)"
	PRODUCTION_BOOTSTRAP_ADMIN_ON_STARTUP=0 PRODUCTION_APP_IMAGE="$(ROLLBACK_APP_IMAGE)" docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file $(PRODUCTION_ENV_FILE) up -d --no-build --no-deps --wait web-production

production-origin-backup:
	COMPOSE_FILE=docker-compose.production.yml COMPOSE_OVERRIDE_FILE=docker-compose.host-nginx.yml COMPOSE_ENV_FILE="$(PRODUCTION_ENV_FILE)" DB_SERVICE=db-production BACKUP_DIR="$(PRODUCTION_BACKUP_DIR)" ./scripts/backup_postgres.sh

production-origin-backup-verify:
	test -n "$(BACKUP_FILE)"
	COMPOSE_FILE=docker-compose.production.yml COMPOSE_OVERRIDE_FILE=docker-compose.host-nginx.yml COMPOSE_ENV_FILE="$(PRODUCTION_ENV_FILE)" DB_SERVICE=db-production BACKUP_FILE="$(BACKUP_FILE)" ./scripts/verify_postgres_backup.sh

production-origin-restore-verify:
	test -n "$(BACKUP_FILE)"
	@image_ref=$$(docker compose -f docker-compose.production.yml -f docker-compose.host-nginx.yml --env-file "$(PRODUCTION_ENV_FILE)" images -q db-production); \
		test -n "$$image_ref"; \
		image_id=$$(docker image inspect --format '{{.Id}}' "$$image_ref"); \
		test -n "$$image_id"; \
		POSTGRES_IMAGE="$$image_id" BACKUP_FILE="$(BACKUP_FILE)" ./scripts/verify_postgres_restore.sh

production-origin-metrics:
	test -n "$(METRICS_DB_USER)"
	COMPOSE_FILE=docker-compose.production.yml COMPOSE_OVERRIDE_FILE=docker-compose.host-nginx.yml COMPOSE_ENV_FILE="$(PRODUCTION_ENV_FILE)" DB_SERVICE=db-production REQUIRE_METRICS_DB_USER=1 METRICS_DB_USER="$(METRICS_DB_USER)" ./scripts/collect_postgres_metrics.sh

alpha-up:
	test -f $(ALPHA_ENV_FILE)
	docker compose -f docker-compose.alpha.yml --env-file $(ALPHA_ENV_FILE) up -d --build --wait

alpha-check:
	python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$(ALPHA_WEB_PORT)/health', timeout=5).read()"
	docker compose -f docker-compose.alpha.yml --env-file $(ALPHA_ENV_FILE) exec -T web-alpha uv run --no-sync flask --app wsgi db current

alpha-e2e:
	@test -n "$(ALPHA_ADMIN_USERNAME)" && test -n "$(ALPHA_ADMIN_PASSWORD)"
	@ADMIN_URL=http://127.0.0.1:$(ALPHA_WEB_PORT) ADMIN_USERNAME="$(ALPHA_ADMIN_USERNAME)" ADMIN_PASSWORD="$(ALPHA_ADMIN_PASSWORD)" SCREENSHOT_DIR=/tmp npm run test:e2e -- e2e/admin.spec.js

alpha-e2e-full:
	@test -n "$(ALPHA_ADMIN_USERNAME)" && test -n "$(ALPHA_ADMIN_PASSWORD)"
	@ADMIN_URL=http://127.0.0.1:$(ALPHA_WEB_PORT) ADMIN_USERNAME="$(ALPHA_ADMIN_USERNAME)" ADMIN_PASSWORD="$(ALPHA_ADMIN_PASSWORD)" SCREENSHOT_DIR=/tmp npm run test:e2e

alpha-status:
	docker compose -f docker-compose.alpha.yml --env-file $(ALPHA_ENV_FILE) ps

alpha-logs:
	docker compose -f docker-compose.alpha.yml --env-file $(ALPHA_ENV_FILE) logs --tail=200 web-alpha db-alpha

alpha-down:
	docker compose -f docker-compose.alpha.yml --env-file $(ALPHA_ENV_FILE) stop web-alpha db-alpha

beta-up:
	test -f $(BETA_ENV_FILE)
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) up -d --build --wait

beta-check:
	python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$(BETA_WEB_PORT)/health', timeout=5).read()"
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) exec -T web-beta uv run --no-sync flask --app wsgi db current
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) exec -T web-beta gunicorn --version

beta-e2e:
	@test -n "$(BETA_ADMIN_USERNAME)" && test -n "$(BETA_ADMIN_PASSWORD)"
	@ADMIN_URL=http://127.0.0.1:$(BETA_WEB_PORT) ADMIN_USERNAME="$(BETA_ADMIN_USERNAME)" ADMIN_PASSWORD="$(BETA_ADMIN_PASSWORD)" SCREENSHOT_DIR=/tmp npm run test:e2e -- e2e/admin.spec.js

beta-e2e-full:
	@test -n "$(BETA_ADMIN_USERNAME)" && test -n "$(BETA_ADMIN_PASSWORD)"
	@ADMIN_URL=http://127.0.0.1:$(BETA_WEB_PORT) ADMIN_USERNAME="$(BETA_ADMIN_USERNAME)" ADMIN_PASSWORD="$(BETA_ADMIN_PASSWORD)" SCREENSHOT_DIR=/tmp npm run test:e2e

beta-status:
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) ps

beta-logs:
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) logs --tail=200 web-beta db-beta

beta-down:
	docker compose -f docker-compose.beta.yml --env-file $(BETA_ENV_FILE) stop web-beta db-beta
