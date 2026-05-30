# Non-sensitive values committed to the repo.
# AWS credentials come from environment variables or GitHub OIDC — never committed here.

s3_bucket = "phl-gun-violence-dashboard"

# Fill in your actual subnet and security group IDs.
# These are VPC-specific and safe to commit (they are not secrets).
vpc_subnet_ids         = ["subnet-REPLACE_ME"]
vpc_security_group_ids = ["sg-REPLACE_ME"]
