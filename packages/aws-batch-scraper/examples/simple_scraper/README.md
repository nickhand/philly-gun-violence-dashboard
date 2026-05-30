# Simple Scraper Example

This package shows the minimum pieces needed to use `aws-batch-scraper`:

- config defaults in `simple_scraper/config.py`
- input loading in `simple_scraper/inputs.py`
- scraper implementation in `simple_scraper/scraper.py`
- CLI construction in `simple_scraper/cli.py`

Run locally after installing the package:

```bash
simple-scraper scraper bench --sample 3 --no-jitter
simple-scraper scraper submit --dry-run --sample 3
```

The Dockerfile templates in `../docker/` show how to package a real scraper for
ECS/Fargate.
