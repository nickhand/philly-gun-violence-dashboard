import json
import posixpath
from io import BytesIO, StringIO
from typing import Any, Literal

import pandas as pd
from loguru import logger

from dashboard_utils.aws import ensure_bucket, exists_on_s3, make_boto3_session, parse_s3_uri
from dashboard_utils.env import get_ecs_settings, s3_settings


class AWS:
    """Connection to Amazon Web Services.

    Attributes
    ----------
    debug : bool
        If ``True``, enable debug logging.
    session : boto3.Session
        Boto3 session.
    ecs : S3Client
        ECS client.
    ec2 : S3Client
        EC2 client.
    s3 : S3Client
        S3 client.
    bucket_name : str
        S3 bucket name.
    cluster_name : str
        ECS cluster name.
    """

    def __init__(self, debug: bool = False) -> None:
        """Initialize the connection to AWS."""
        self.debug = debug
        ecs_settings = get_ecs_settings()

        # Set up the AWS session
        self.session = make_boto3_session()

        # Set up clients
        self.ecs = self.session.client("ecs")
        self.ec2 = self.session.client("ec2")
        self.s3 = self.session.client("s3")

        # Set up the output s3 bucket (and create it if we need to)
        self.bucket_name = s3_settings.AWS_BUCKET_NAME
        ensure_bucket(self.s3, self.bucket_name)

        # Set up cluster
        self.cluster_name = ecs_settings.ECS_CLUSTER_NAME
        self._ecs_settings = ecs_settings

    def _init_cluster(self) -> None:
        """Initialize the ECS cluster."

        This function initialize the cluster by:
        - Verifying that the cluster exists
        - Getting the subnets
        - Getting the latest task definition
        """
        # Verify that the cluster exists
        clusters = self.ecs.list_clusters()
        cluster_names = [c.split("/")[-1] for c in clusters["clusterArns"]]
        if self.cluster_name not in cluster_names:
            raise ValueError(f"Missing ECS cluster: {self.cluster_name}")

        # Get the subnets
        self.subnets = [d["SubnetId"] for d in self.ec2.describe_subnets()["Subnets"]]
        if self.debug:
            logger.info(f"Subnets: {self.subnets}")

        # Get the latest task definition
        prefix = self._ecs_settings.ECS_CLUSTER_NAME.rsplit("-", 1)[0]
        tasks = self.ecs.list_task_definitions(familyPrefix=prefix, sort="ASC")
        self.task_definition = tasks["taskDefinitionArns"][-1]

        if self.debug:
            logger.info(f"Task definition: {self.task_definition}")

    def submit_jobs(
        self,
        input_filename: str,
        output_folder: str,
        search_by: Literal["Incident Number", "Docket Number"] = "Incident Number",
        shard_id: int | None = None,
        dry_run: bool = False,
        sample: int | None = None,
        log_freq: int = 50,
        seed: int = 42,
        errors: Literal["raise", "ignore"] = "ignore",
        sleep: int = 2,
        debug: bool = False,
        ntasks: int = 1,
        wait: bool = False,
        run_id: str | None = None,
        no_retry: bool = False,
        screenshots: bool = True,
    ) -> str | None:
        """Submit jobs to the ECS cluster.

        Parameters
        ----------
        input_filename : str
            S3 path to the input filename.
        output_folder : str
            S3 path to the shards folder (e.g., 's3://bucket/runs/{run_id}/shards').
        search_by : str, optional
            Portal search field.
        shard_id : int, optional
            Worker id (0-indexed).
        dry_run : bool, optional
            Do everything except write outputs.
        sample : int, optional
            Sample this many records before scraping.
        log_freq : int, optional
            Log every N portal requests.
        seed : int, optional
            Random seed for sampling.
        errors : str, optional
            Error handling mode.
        sleep : int, optional
            Delay between portal requests.
        debug : bool, optional
            Verbose logging.
        ntasks : int, optional
            Total parallel splits.
        wait : bool, optional
            Wait for all tasks to complete.
        run_id : str, optional
            Run identifier for audit logging.
        no_retry : bool, optional
            Disable retry mechanism (max_attempts=1) for debugging.
        screenshots : bool, optional
            Enable/disable screenshots for failures.

        Returns
        -------
        str | None
            S3 path to the combined output file or None if not waiting.
        """
        # Init if we need to
        if not hasattr(self, "subnets"):
            self._init_cluster()

        # Set the network config
        NETWORK_CONFIG = {
            "awsvpcConfiguration": {
                "assignPublicIp": "ENABLED",
                "subnets": self.subnets,
            }
        }

        # Log
        if debug:
            logger.debug(f"Output folder: {output_folder}")

        # Build the base command
        # NOTE: ENTRYPOINT already runs `uv run gv-dashboard-etl courts batch`
        base_command = [
            "uv",
            "run",
            "gv-dashboard-etl",
            "courts",
            "batch",
            input_filename,  # This MUST be an s3 path
            output_folder,  # This MUST be an s3 path (shards folder)
            f"--nprocs={ntasks}",
            f"--sleep={sleep}",
            f"--errors={errors}",
            f"--log-freq={log_freq}",
            f"--seed={seed}",
        ]

        # Add the optional arguments
        if search_by is not None:
            base_command += [f"--search-by={search_by}"]
        if sample is not None:
            base_command += [f"--sample={sample}"]
        if dry_run:
            base_command += ["--dry-run"]
        if debug:
            base_command += ["--debug"]
        if run_id is not None:
            base_command += [f"--run-id={run_id}"]
        if no_retry:
            base_command += ["--no-retry"]
        if not screenshots:
            base_command += ["--no-screenshots"]

        # Pass settings via environment variables to ECS tasks
        # NOTE: skip AWS credentials since those are handled by the ECS task role
        skipfields = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
        env_vars = [
            {"name": k, "value": v}
            for k, v in s3_settings.model_dump().items()
            if k not in skipfields
        ]

        # Add ECS-specific settings
        keys = ["ECS_CLUSTER_NAME", "CONTAINER_NAME"]
        for k in keys:
            v = getattr(self._ecs_settings, k)
            env_vars.append({"name": k, "value": v})

        # Run in parallel
        tasks = []
        for shard_id in range(0, ntasks):
            # Log
            logger.info(f"Submitting job shard-{shard_id:02d}")

            # Build the final command
            command = base_command + [f"--shard-id={shard_id}"]

            # Submit job
            task = self.ecs.run_task(
                taskDefinition=self.task_definition,
                cluster=self.cluster_name,
                networkConfiguration=NETWORK_CONFIG,
                launchType="FARGATE",
                overrides={
                    "containerOverrides": [
                        {
                            "name": self._ecs_settings.CONTAINER_NAME,
                            "command": command,
                            "environment": [{"name": "ENV", "value": "prod"}] + env_vars,
                        }
                    ]
                },
            )

            tasks.append(task)

        # Do not wait for tasks to finish
        if not wait:
            return None

        # Check if provisioning failed:
        failed = False
        for task in tasks:
            if not len(task["tasks"]) and len(task["tasks"]["failures"]):
                failed = True
                reason = task["tasks"]["failures"][0]["reason"]
                logger.warning(f"Task provisioning failed: {reason}")

        # Trim to successful tasks
        tasks = [task for task in tasks if len(task["tasks"])]

        # Stop successful
        if failed:
            for task in tasks:
                self.ecs.stop_task(cluster=self.cluster_name, task=task["tasks"][0]["taskArn"])
            raise ValueError("Error provisioning some tasks; all tasks stopped.")

        # Get the task ids
        task_ids = [task["tasks"][0]["taskArn"] for task in tasks]

        # Wait for all jobs to complete
        logger.info("Waiting for tasks to complete")
        waiter = self.ecs.get_waiter("tasks_stopped")
        waiter.wait(
            cluster=self.cluster_name,
            tasks=task_ids,
            WaiterConfig={"Delay": 60, "MaxAttempts": 500},
        )
        logger.info("...all tasks completed")

        # Check for errors
        task_results = self.ecs.describe_tasks(cluster=self.cluster_name, tasks=task_ids)

        # Check the exit codes and log failures
        failed_shards = []
        for i, task in enumerate(task_results["tasks"]):
            exit_code = task["containers"][0].get("exitCode")
            if exit_code != 0:
                failed_shards.append(i)
                reason = task["containers"][0].get("reason", "Unknown")
                logger.warning(f"Shard {i} failed with exit code {exit_code}: {reason}")

        if failed_shards:
            logger.warning(
                f"{len(failed_shards)}/{ntasks} tasks failed. "
                "Combining results from successful shards..."
            )

        # Still combine results from successful shards
        logger.info("Combining parallel results on AWS")

        # Combine shards and write to merged/ folder
        # output_folder is the shards folder: s3://bucket/runs/{run_id}/shards
        outfile = self.combine_parallel_results(output_folder)

        return outfile

    def combine_parallel_results(self, shards_folder: str) -> str | None:
        """Iterate through parallel, shard scraping results from AWS.

        Parameters
        ----------
        shards_folder : str
            S3 path to the shards folder containing per-shard results.

        Returns
        -------
        str | None
            S3 path to the combined output file or None if not waiting.
        """
        if not exists_on_s3(self.s3, shards_folder.rstrip("/")):
            raise FileNotFoundError(
                f"Shards folder does not exist for parallel results: '{shards_folder}'"
            )

        # New folder structure:
        # - Read from: shards/shard-{NN}/{results,input,errors}
        # - Write to: merged/{portal_results,portal_input,errors}

        # File mappings: (shard_filename, merged_filename)
        file_mappings = [
            ("results.json", "portal_results.json"),
            ("input.csv", "portal_input.csv"),
            ("errors.json", "errors.json"),
        ]

        bucket, shards_prefix = parse_s3_uri(shards_folder.rstrip("/"))
        # merged/ is a sibling of shards/
        run_prefix = shards_prefix.rsplit("/", 1)[0] if "/" in shards_prefix else ""
        merged_prefix = f"{run_prefix}/merged" if run_prefix else "merged"

        # Combine files for each tag
        data_file = None
        for i, (shard_filename, merged_filename) in enumerate(file_mappings):
            extension = "." + shard_filename.rsplit(".", 1)[-1]

            # List all shard-{NN}/ subdirectories and find the file in each
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=f"{shards_prefix}/shard-")

            # Get the list of relevant files from paginated results
            files = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith(f"/{shard_filename}"):
                        files.append(key)

            # Sorted list of files to combine
            files = sorted(files)
            if not files:
                raise ValueError(
                    f"No {shard_filename} files found in shards folder '{shards_folder}'"
                )

            # Log the first time
            if i == 0:
                logger.info(f"Combining {len(files)} shards from AWS")

            # Initialize results
            # -> dict for JSON dicts, list for JSON lists, DataFrame for CSVs
            results: dict[str, Any] | list[Any] | pd.DataFrame | None = None

            # Combine all files
            for key in files:
                # Get the object and read its body
                response = self.s3.get_object(Bucket=bucket, Key=key)
                body = response["Body"].read()

                ## JSON data
                if extension == ".json":
                    r = json.loads(body)

                    # Results are either dicts or lists
                    ## Dict results
                    if isinstance(r, dict):
                        if results is None:
                            results = {}
                        if not isinstance(results, dict):
                            raise TypeError("Expected dict results when combining JSON dicts")
                        results.update(r)
                    ## List results
                    else:
                        if results is None:
                            results = []
                        if not isinstance(results, list):
                            raise TypeError("Expected list results when combining JSON lists")
                        results += r
                ## CSV data
                else:
                    r = pd.read_csv(BytesIO(body), header=None)
                    if results is None:
                        results = r
                    else:
                        assert isinstance(results, pd.DataFrame)
                        results = pd.concat([results, r])

            # Write the combined results to merged/ folder
            output_key = f"{merged_prefix}/{merged_filename}"
            filename = f"s3://{bucket}/{posixpath.normpath(output_key)}"

            # Make sure we have results
            assert results is not None

            # Log the first time (portal_results.json)
            if i == 0:
                data_file = filename
                logger.info(f"Total number of results from AWS: {len(results)}")
                logger.info(f"Saving combined results to {filename}")

            # Save the combined results
            ## JSON
            if extension == ".json":
                payload = json.dumps(results)
            ## CSV
            else:
                assert isinstance(results, pd.DataFrame)
                buf = StringIO()
                results.to_csv(buf, header=False, index=False)
                payload = buf.getvalue()

            self.s3.put_object(Bucket=bucket, Key=output_key, Body=payload.encode())

        # Merge audit files if they exist (verification mode)
        self._merge_audit_files(bucket, shards_prefix, merged_prefix)

        return data_file

    def _merge_audit_files(self, bucket: str, shards_prefix: str, merged_prefix: str) -> None:
        """Merge audit files from all shards into merged/audit/.

        Parameters
        ----------
        bucket : str
            S3 bucket name.
        shards_prefix : str
            S3 prefix for shards folder (e.g., 'courts-scraper/runs/{run_id}/shards').
        merged_prefix : str
            S3 prefix for merged folder (e.g., 'courts-scraper/runs/{run_id}/merged').
        """
        import gzip

        # Find all audit/final.ndjson.gz files in shard folders
        paginator = self.s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=f"{shards_prefix}/shard-")

        audit_files: list[str] = []
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Match audit/final.ndjson.gz or audit/final.ndjson
                if "/audit/final.ndjson" in key:
                    audit_files.append(key)

        if not audit_files:
            logger.debug("No audit files found in shards - skipping audit merge")
            return

        audit_files = sorted(audit_files)
        logger.info(f"Merging audit files from {len(audit_files)} shards")

        # Read and merge all audit records
        all_records: list[dict[str, Any]] = []
        for key in audit_files:
            response = self.s3.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()

            # Decompress if gzipped
            if key.endswith(".gz"):
                body = gzip.decompress(body)

            # Parse NDJSON
            for line in body.decode("utf-8").split("\n"):
                if line.strip():
                    all_records.append(json.loads(line))

        logger.info(f"Merged {len(all_records)} audit records from all shards")

        # Write merged audit file to merged/audit/final_merged.ndjson.gz
        audit_output_key = f"{merged_prefix}/audit/final_merged.ndjson.gz"

        # Serialize to NDJSON and compress
        ndjson_content = "\n".join(json.dumps(r, separators=(",", ":")) for r in all_records)
        compressed = gzip.compress(ndjson_content.encode("utf-8"))

        self.s3.put_object(Bucket=bucket, Key=audit_output_key, Body=compressed)
        logger.info(f"Saved merged audit file to s3://{bucket}/{audit_output_key}")
