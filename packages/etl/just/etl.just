# ETL recipes.

# ETL boundaries data
[group: "etl"]
etl-boundaries:
	cd packages/etl; uv run gv-dashboard-etl boundaries extract

# ETL shootings data
[group: "etl"]
etl-shootings:
	cd packages/etl; uv run gv-dashboard-etl shootings update

# Check the live shootings source without writing outputs
[group: "etl"]
etl-shootings-smoke:
	cd packages/etl; uv run gv-dashboard-etl shootings smoke

# ETL homicides data
[group: "etl"]
etl-homicides:
	cd packages/etl; uv run gv-dashboard-etl homicides update

# Check the live homicide source without writing outputs
[group: "etl"]
etl-homicides-smoke:
	cd packages/etl; uv run gv-dashboard-etl homicides smoke

# ETL streets data
[group: "etl"]
etl-streets:
	cd packages/etl; uv run gv-dashboard-etl streets extract && uv run gv-dashboard-etl streets load

# ETL courts data - incremental, launches ECS monitor to finalize and dispatch processing
[group: "etl"]
etl-courts:
	cd packages/etl; uv run gv-dashboard-etl courts submit --monitor-in-ecs

# ETL courts data - full weekly re-scrape, launches ECS monitor to finalize and dispatch processing
[group: "etl"]
etl-courts-full:
	cd packages/etl; uv run gv-dashboard-etl courts submit --force --monitor-in-ecs

# ETL courts data - aggregate results and write processed flags CSV
[group: "etl"]
etl-courts-process:
	cd packages/etl; uv run gv-dashboard-etl courts process

# Check courts AWS config and UJS portal access without writing outputs
[group: "etl"]
etl-courts-smoke *ARGS:
	cd packages/etl; uv run gv-dashboard-etl courts smoke {{ARGS}}
