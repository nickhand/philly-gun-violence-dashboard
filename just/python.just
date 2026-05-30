# Python workspace tooling recipes.

python_packages := "api dashboard-utils etl aws-batch-scraper"

# Lint the codebase
[group: "lint"]
lint package="all":
	@if [ "{{package}}" = "all" ]; then \
		for package in {{python_packages}}; do \
			echo "Linting $$package..."; \
			case "$$package" in \
				api) cd packages/api && uv run --group dev ruff check --fix app && cd ../.. ;; \
				dashboard-utils) cd packages/dashboard-utils && uv run --group dev ruff check --fix src && cd ../.. ;; \
				etl) cd packages/etl && uv run --group dev ruff check --fix src && cd ../.. ;; \
				aws-batch-scraper) cd packages/aws-batch-scraper && uv run --group dev ruff check --fix src && cd ../.. ;; \
			esac; \
		done; \
	elif [ "{{package}}" = "api" ]; then \
		cd packages/api && uv run --group dev ruff check --fix app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd packages/dashboard-utils && uv run --group dev ruff check --fix src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd packages/etl && uv run --group dev ruff check --fix src; \
	elif [ "{{package}}" = "aws-batch-scraper" ]; then \
		cd packages/aws-batch-scraper && uv run --group dev ruff check --fix src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi

# Format the codebase
[group: "lint"]
format package="all":
	@if [ "{{package}}" = "all" ]; then \
		for package in {{python_packages}}; do \
			echo "Formatting $$package..."; \
			case "$$package" in \
				api) cd packages/api && uv run --group dev ruff format app && cd ../.. ;; \
				dashboard-utils) cd packages/dashboard-utils && uv run --group dev ruff format src && cd ../.. ;; \
				etl) cd packages/etl && uv run --group dev ruff format src && cd ../.. ;; \
				aws-batch-scraper) cd packages/aws-batch-scraper && uv run --group dev ruff format src && cd ../.. ;; \
			esac; \
		done; \
	elif [ "{{package}}" = "api" ]; then \
		cd packages/api && uv run --group dev ruff format app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd packages/dashboard-utils && uv run --group dev ruff format src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd packages/etl && uv run --group dev ruff format src; \
	elif [ "{{package}}" = "aws-batch-scraper" ]; then \
		cd packages/aws-batch-scraper && uv run --group dev ruff format src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi

# Run mypy type checks
[group: "lint"]
typecheck package="all":
	@if [ "{{package}}" = "all" ]; then \
		for package in {{python_packages}}; do \
			echo "Type-checking $$package..."; \
			case "$$package" in \
				api) cd packages/api && uv run --group dev mypy --config-file ../../mypy.ini app && cd ../.. ;; \
				dashboard-utils) cd packages/dashboard-utils && uv run --group dev mypy --config-file ../../mypy.ini src && cd ../.. ;; \
				etl) cd packages/etl && uv run --group dev mypy --config-file ../../mypy.ini src && cd ../.. ;; \
				aws-batch-scraper) cd packages/aws-batch-scraper && uv run --group dev mypy --config-file ../../mypy.ini src && cd ../.. ;; \
			esac; \
		done; \
	elif [ "{{package}}" = "api" ]; then \
		cd packages/api && uv run --group dev mypy --config-file ../../mypy.ini app; \
	elif [ "{{package}}" = "dashboard-utils" ]; then \
		cd packages/dashboard-utils && uv run --group dev mypy --config-file ../../mypy.ini src; \
	elif [ "{{package}}" = "etl" ]; then \
		cd packages/etl && uv run --group dev mypy --config-file ../../mypy.ini src; \
	elif [ "{{package}}" = "aws-batch-scraper" ]; then \
		cd packages/aws-batch-scraper && uv run --group dev mypy --config-file ../../mypy.ini src; \
	else \
		echo "Unknown package: {{package}}" >&2; \
		exit 1; \
	fi
