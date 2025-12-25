import inspect
from typing import Literal, cast

import numpy as np
import pandas as pd
from etl.courts.batch import io
from etl.courts.batch.aws import AWS
from etl.courts.portal.core import UJSPortalScraper
from etl.courts.portal.schema import PortalResult
from loguru import logger


def _scrape(
    data: pd.Series,
    search_by: Literal["Incident Number", "Docket Number"] = "Incident Number",
    sleep: int = 7,
    log_freq: int = 50,
    errors: Literal["ignore", "raise"] = "ignore",
    debug: bool = False,
) -> tuple[dict[str, list[PortalResult] | None], list[str]]:
    """Scrape incident/docket info from the UJS portal.

    Returns
    -------
    dict[str, list[PortalResult] | None]
        Dictionary mapping input values to their scraped results (or None)
    """
    if debug:
        logger.debug(
            "Initializing portal scraper: "
            "search_by={search_by}, sleep={sleep}, log_freq={log_freq}, errors={errors}"
        )

    # Initialize the scraper
    scraper = UJSPortalScraper(
        search_by=search_by,
        sleep=sleep,
        log_freq=log_freq,
        errors=errors,
        debug=debug,
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
    pid: int | None = None,
    dry_run: bool = False,
    sample: int | None = None,
    log_freq: int = 50,
    seed: int = 42,
    errors: Literal["raise", "ignore"] = "ignore",
    sleep: int = 7,
    debug: bool = False,
) -> None:
    """
    Scrape portal data in batch (optionally split across workers).

    Parameters
    ----------
    input_filename :
        The name of the input filename with data to process
    output_folder :
        The name of the output folder to save the results
    nprocs : optional
        The total number of processors running the scraper
    pid : optional
        The id for this processor
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
    data = io.load_input_data(input_filename=input_filename, aws=aws)
    if debug:
        logger.debug("...done")

    # Sample it if requested
    if sample is not None:
        data = data.sample(sample, random_state=seed)

    # Split data
    if nprocs is None:
        nprocs = 1
    if pid is None:
        pid = 0

    assert pid < nprocs

    # Split the data for this worker
    # NOTE: data_chunk is a pd.Series
    if nprocs > 1:
        data_chunk = cast(pd.Series, np.array_split(data, nprocs)[pid])
        chunk = pid
    else:
        data_chunk = data
        chunk = None

    # No data, then return
    if not len(data_chunk):
        return

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
    )
    if debug:
        logger.debug("...done")

    # Save!
    if not dry_run:
        # Get output folder and output path for results
        output_folder, outfile = io.get_output_paths(
            output_folder=output_folder,
            chunk=chunk,
        )

        if debug:
            logger.debug(f"Saving results to {outfile}")

        # Serialize the PortalResult objects to dicts
        results_dict = {
            k: [r.model_dump() for r in v] if v is not None else None for k, v in results.items()
        }
        # Save the results to portal_results[_chunk].json
        io.save_output_data(outfile, results=results_dict, aws=aws)

        # Get the input config
        local_variables = locals()
        frame = inspect.currentframe()
        fname = inspect.getframeinfo(frame).function if frame is not None else "scrape"
        if fname in globals():
            sig = inspect.signature(globals()[fname])
            config = {p: local_variables[p] for p in sig.parameters}
        else:
            config = {}

        # Save the config and input
        if chunk is not None:
            io.save_output_data(
                f"{output_folder}/config_{chunk}.json",
                results=config,
                aws=aws,
            )
            io.save_output_data(
                f"{output_folder}/portal_input_{chunk}.csv",
                results=data_chunk,
                aws=aws,
            )
            io.save_output_data(
                f"{output_folder}/errors_{chunk}.json",
                results=errors_list,
                aws=aws,
            )
        else:
            io.save_output_data(
                f"{output_folder}/config.json",
                results=config,
                aws=aws,
            )
            io.save_output_data(
                f"{output_folder}/portal_input.csv",
                results=data_chunk,
                aws=aws,
            )
            io.save_output_data(
                f"{output_folder}/errors.json",
                results=errors_list,
                aws=aws,
            )
        if debug:
            logger.debug("...done")
