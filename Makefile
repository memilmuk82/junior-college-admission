PYTHON := uv run
TEST_DATABASE_URL := postgresql+psycopg://admission_test:test-only-password@127.0.0.1:$${TEST_POSTGRES_PORT:-55432}/admission_test
COMPOSE_TEST_ENV := SECRET_KEY=test-only-secret DATABASE_URL=$(TEST_DATABASE_URL) POSTGRES_PASSWORD=test-only-password

.PHONY: setup test-unit test-integration test-e2e lint validate-rules check-sensitive-data check

setup:
	uv sync --frozen
	npm ci

test-unit:
	$(PYTHON) pytest tests/test_admin_auth.py tests/test_admission_results.py tests/test_rule_admin.py tests/test_score_rule_csv_preview.py tests/test_app.py tests/test_application_policies.py tests/test_eligibility.py tests/test_image_imports.py tests/test_pilot_candidates.py tests/test_pilot_golden_candidates.py tests/test_review_forms.py tests/test_review_state.py tests/test_scanned_pdf_imports.py tests/test_score_calculation.py tests/test_score_components.py tests/test_score_conversion.py tests/test_score_golden.py tests/test_score_inputs.py tests/test_score_properties.py tests/test_score_rule_schema.py tests/test_score_selection.py tests/test_structured_imports.py tests/test_temporary_uploads.py tests/test_text_pdf_imports.py tests/test_validate_rules.py

test-integration:
	$(COMPOSE_TEST_ENV) docker compose --profile test rm -f -s -v db-test
	$(COMPOSE_TEST_ENV) docker compose --profile test up -d --wait db-test
	@status=0; TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTHON) pytest tests/test_admin_rule_routes.py tests/test_score_rule_csv_drafts.py tests/test_admission_result_models.py tests/test_rule_admin_models.py tests/test_confirmed_imports.py tests/test_database.py tests/test_migrations.py tests/test_models.py tests/test_published_rules.py tests/test_review_routes.py || status=$$?; \
		$(COMPOSE_TEST_ENV) docker compose --profile test rm -f -s -v db-test; \
		exit $$status

test-e2e:
	npm run test:e2e

lint:
	$(PYTHON) ruff check .
	$(PYTHON) ruff format --check .
	$(PYTHON) mypy app scripts tests

validate-rules:
	$(PYTHON) python -m scripts.validate_rules

check-sensitive-data:
	$(PYTHON) python scripts/check_sensitive_data.py

check: lint test-unit test-integration validate-rules check-sensitive-data
