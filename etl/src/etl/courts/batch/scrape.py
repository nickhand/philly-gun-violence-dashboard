import inspect

import numpy as np
from loguru import logger

from etl.courts.portal.core import UJSPortalScraper

from . import io
from .aws import AWS


def _scrape(
    data,
    search_by=None,
    sleep: int = 7,
    log_freq: int = 50,
    errors: str = "ignore",
    debug: bool = False,
):
    """Scrape incident/docket info from the UJS portal."""

    if debug:
        logger.debug(
            f"Initializing portal scraper: search_by={search_by}, sleep={sleep}, log_freq={log_freq}, errors={errors}"
        )
    scraper = UJSPortalScraper(
        search_by=search_by,
        sleep=sleep,
        log_freq=log_freq,
        errors=errors,
        debug=debug,
    )

    if debug:
        logger.debug(f"Scraping portal data for {len(data)} rows")
    results = scraper.scrape_portal_data(data.values)
    if debug:
        logger.debug("...done")

    return results


def scrape(
    input_filename: str,
    output_folder: str,
    search_by: str | None = None,
    nprocs: int | None = None,
    pid: int | None = None,
    dry_run: bool = False,
    sample: int | None = None,
    log_freq: int = 50,
    seed: int = 42,
    errors: str = "ignore",
    sleep: int = 7,
    debug: bool = False,
):
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
    assert pid < nprocs
    if nprocs > 1:
        data_chunk = np.array_split(data, nprocs)[pid]
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
    results = _scrape(
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

        # Get output folder and data path
        output_folder, outfile = io.get_output_paths(
            output_folder=output_folder,
            chunk=chunk,
        )

        if debug:
            logger.debug(f"Saving results to {outfile}")

        # Save the results
        io.save_output_data(outfile, results, aws=aws)

        # Get the input config
        local_variables = locals()
        frame = inspect.currentframe()
        fname = inspect.getframeinfo(frame).function
        sig = inspect.signature(globals()[fname])
        config = {p: local_variables[p] for p in sig.parameters}

        # Save the config and input
        if chunk is not None:
            io.save_output_data(f"{output_folder}/config_{chunk}.json", config, aws=aws)
            io.save_output_data(
                f"{output_folder}/portal_input_{chunk}.csv", data_chunk, aws=aws
            )
        else:
            io.save_output_data(f"{output_folder}/config.json", config, aws=aws)
            io.save_output_data(
                f"{output_folder}/portal_input.csv", data_chunk, aws=aws
            )

        if debug:
            logger.debug("...done")
