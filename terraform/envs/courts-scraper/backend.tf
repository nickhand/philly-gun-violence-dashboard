terraform {
  backend "s3" {
    # Bucket must already exist. Reuses the project's existing data bucket.
    # State key is scoped to this environment so other stacks won't collide.
    bucket = "phl-gun-violence-dashboard"
    key    = "terraform/courts-scraper/terraform.tfstate"
    region = "us-east-1"
  }
}
