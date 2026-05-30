# Data recipes.

# Sync the S3 data bucket to the local data/ folder
[group: "data"]
data-sync:
	aws s3 sync s3://{{env("S3_BUCKET")}} data/ --exact-timestamps --delete
