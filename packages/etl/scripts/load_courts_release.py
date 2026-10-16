"""Resolve the atomic production release into this GitHub job's environment."""

import os
from pathlib import Path

import boto3

from etl.courts.deployment import load_release_environment

if __name__ == "__main__":
    session = boto3.Session(region_name=os.environ["AWS_REGION"])
    pins = load_release_environment(session.client("s3"), session.client("ecs"))
    with Path(os.environ["GITHUB_ENV"]).open("a") as output:
        for name, value in pins.items():
            if "\n" in value or "\r" in value:
                raise ValueError("Invalid release pin")
            output.write(f"{name}={value}\n")
