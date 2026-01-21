import inspect
from typing import Literal, cast

import numpy as np
import pandas as pd
from loguru import logger

from etl.courts.batch import io
from etl.courts.batch.aws import AWS
from etl.courts.scraper.core import UJSPortalScraper
from etl.courts.scraper.schema import PortalResult


def _scrape(
    data: pd.Series,
    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number",
    sleep: int = 7,
    log_freq: int = 50,
    errors: Literal["ignore", "raise"] = "ignore",
    debug: bool = False,
    verify: bool = False,
    audit_output_dir: str | None = None,
    shard_id: int = 0,
    shard_count: int = 1,
    run_id: str | None = None,
    no_retry: bool = False,
) -> tuple[dict[str, list[PortalResult] | None], list[str]]:
    """Scrape incident/docket info from the UJS portal.

    Parameters
    ----------
    data : pd.Series
        Series of incident/docket numbers to scrape.
    search_by : str
        Search field type.
    sleep : int
        Sleep between requests.
    log_freq : int
        Log frequency.
    errors : str
        Error handling mode.
    debug : bool
        Debug mode.
    verify : bool
        Enable verification mode with audit logging.
    audit_output_dir : str | None
        Directory for audit output files (verification mode only).
    shard_id : int
        Shard index for distributed scraping.
    shard_count : int
        Total number of shards.
    run_id : str | None
        Run identifier for audit logging.
    no_retry : bool
        Disable retry mechanism (sets max_attempts=1).

    Returns
    -------
    tuple[dict[str, list[PortalResult] | None], list[str]]
        Dictionary mapping input values to their scraped results (or None),
        and list of input values that encountered errors.
    """
    if debug:
        logger.debug(
            f"Initializing portal scraper: "
            f"search_by={search_by}, sleep={sleep}, log_freq={log_freq}, "
            f"errors={errors}, verify={verify}"
        )

    # Build audit context if verification enabled (for audit log metadata)
    audit_context = None
    if verify:
        from etl.courts.verification.shard import AuditContext

        audit_context = AuditContext(
            run_id=run_id or "",
            shard_id=shard_id,
            shard_count=shard_count,
            task_id=f"batch-{shard_id}",
        )

    # Initialize the scraper
    scraper = UJSPortalScraper(
        search_by=search_by,
        sleep=sleep,
        log_freq=log_freq,
        errors=errors,
        debug=debug,
        verify=verify,
        audit_output_dir=audit_output_dir,
        audit_context=audit_context,
        max_attempts=1 if no_retry else 8,
    )

    # Scrape the data
    if debug:
        logger.debug(f"Scraping portal data for {len(data)} rows")
    results, errors_list = scraper.scrape_portal_data(data.tolist())
    if debug:
        logger.debug("...done")

    return results, errors_list


def scrape(
    input_filename: str,
    output_folder: str,
    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number",
    nprocs: int | None = None,
    shard_id: int | None = None,
    dry_run: bool = False,
    sample: int | None = None,
    log_freq: int = 50,
    seed: int = 42,
    errors: Literal["raise", "ignore"] = "ignore",
    sleep: int = 7,
    debug: bool = False,
    verify: bool = False,
    run_id: str | None = None,
    no_retry: bool = False,
) -> None:
    """
    Scrape portal data in batch (optionally split across workers).

    Parameters
    ----------
    input_filename :
        The name of the input filename with data to process
    output_folder :
        The shards folder to save outputs (e.g., 's3://bucket/runs/{run_id}/shards')
    nprocs : optional
        The total number of processors running the scraper
    shard_id : optional
        The id for this shard/processor (0-indexed)
    dry_run : optional
        Do not save any results if `True`
    sample : optional
        Use a random sub-sample of the input data
    log_freq : optional
        Log updates for every N requests
    seed : optional
        Set the random seed
    errors : optional
        How to handle exceptions raised during scraping
    sleep: optional
        How long to wait between scraping calls
    verify : optional
        Enable verification mode with audit logging
    run_id : optional
        Run identifier for audit logging (verification mode)
    no_retry : optional
        Disable retry mechanism (max_attempts=1) for debugging
    """
    # Initialize the AWS connection
    if debug:
        logger.debug("Initializing AWS connection")
    aws = AWS()
    if debug:
        logger.debug("...done")

    # Load input data
    if debug:
        logger.debug("Loading input data")
    data = io.load_input_data(aws.s3, input_filename=input_filename, aws=aws)
    if debug:
        logger.debug("...done")

    # Sample it if requested
    if sample is not None:
        data = data.sample(sample, random_state=seed)

    # Split data
    if nprocs is None:
        nprocs = 1
    if shard_id is None:
        shard_id = 0

    assert shard_id < nprocs

    # Split the data for this worker
    # NOTE: data_chunk is a pd.Series
    if nprocs > 1:
        data_chunk = cast(pd.Series, np.array_split(data, nprocs)[shard_id])
        current_shard: int | None = shard_id
    else:
        data_chunk = data
        current_shard = None

    # No data, then return
    if not len(data_chunk):
        return

    # Determine audit output directory for verification mode
    # Audit files go inside the shard folder: shards/shard-{NN}/audit/
    audit_output_dir: str | None = None
    if verify and current_shard is not None:
        audit_output_dir = f"{output_folder}/shard-{current_shard:02d}"
    elif verify:
        audit_output_dir = output_folder

    # Run the scraper
    if debug:
        logger.debug("Starting to scrape the data")
    results, errors_list = _scrape(
        data_chunk,
        search_by=search_by,
        sleep=sleep,
        log_freq=log_freq,
        errors=errors,
        debug=debug,
        verify=verify,
        audit_output_dir=audit_output_dir,
        shard_id=shard_id,
        shard_count=nprocs,
        run_id=run_id,
        no_retry=no_retry,
    )
    if debug:
        logger.debug("...done")

    # Save!
    if not dry_run:
        # Get output folder and output path for results
        shard_folder, outfile = io.get_output_paths(
            output_folder=output_folder, shard_id=current_shard
        )

        if debug:
            logger.debug(f"Saving results to {outfile}")

        # Serialize the PortalResult objects to dicts
        results_dict = {
            k: [r.model_dump() for r in v] if v is not None else None for k, v in results.items()
        }
        # Save the results to results.json
        io.save_output_data(aws, outfile=outfile, results=results_dict)

        # Get the input config
        local_variables = locals()
        frame = inspect.currentframe()
        fname = inspect.getframeinfo(frame).function if frame is not None else "scrape"
        if fname in globals():
            sig = inspect.signature(globals()[fname])
            config = {p: local_variables[p] for p in sig.parameters}
        else:
            config = {}

        # Save the config and input within the shard folder
        if current_shard is not None:
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/config.json",
                results=config,
            )
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/input.csv",
                results=data_chunk,
            )
            # Serialize error objects to dicts
            errors_dicts = [e.model_dump(mode="json") for e in errors_list]
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/errors.json",
                results=errors_dicts,
            )
        else:
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/config.json",
                results=config,
            )
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/input.csv",
                results=data_chunk,
            )
            # Serialize error objects to dicts
            errors_dicts = [e.model_dump(mode="json") for e in errors_list]
            io.save_output_data(
                aws,
                outfile=f"{shard_folder}/errors.json",
                results=errors_dicts,
            )
        if debug:
            logger.debug("...done")
