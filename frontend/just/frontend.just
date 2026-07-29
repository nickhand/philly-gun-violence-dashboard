# Frontend recipes.

# Install frontend dependencies
[group: "ui"]
ui-install:
	cd frontend; npm install

# Build the frontend application
[group: "ui"]
ui-build:
	cd frontend; npm run build

# Launch the development server for the frontend
[group: "ui"]
ui-dev:
	cd frontend; npm run dev

# Type check the frontend application
[group: "ui"]
ui-type-check:
	cd frontend; npm run type-check

# Lint the frontend (alias for type-check)
[group: "ui"]
ui-lint:
	cd frontend; npm run type-check

# Run frontend unit and component tests
[group: "ui"]
ui-test:
	cd frontend; npm test

# Run frontend tests with coverage
[group: "ui"]
ui-test-coverage:
	cd frontend; npm run test:coverage

# Run frontend end-to-end tests in all configured browsers
[group: "ui"]
ui-test-e2e:
	cd frontend; npm run test:e2e
