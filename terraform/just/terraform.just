# Terraform recipes.

TF_ENV := "courts-scraper"

# Initialize Terraform for the given environment
[group: "terraform"]
terraform-init env=TF_ENV:
	terraform -chdir=terraform/envs/{{env}} init

# Preview Terraform changes for the given environment
[group: "terraform"]
terraform-plan env=TF_ENV:
	terraform -chdir=terraform/envs/{{env}} plan

# Apply Terraform changes for the given environment
[group: "terraform"]
terraform-apply env=TF_ENV:
	terraform -chdir=terraform/envs/{{env}} apply
