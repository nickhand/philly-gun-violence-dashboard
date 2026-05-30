"""Load incidents from the shootings database as WorkItems for the scraper framework."""

from aws_batch_scraper.aws import make_boto3_session
from aws_batch_scraper.config import SubmitterConfig
from aws_batch_scraper.types import WorkItem


def load_incidents(config: SubmitterConfig) -> list[WorkItem]:
    """Return all unique incident numbers from the shootings database as WorkItems.

    Parameters
    ----------
    config
        Submitter configuration; used to resolve S3 credentials for loading the
        shootings database.

    Returns
    -------
    list[WorkItem]
        One WorkItem per unique dc_key (incident number).
    """
    from etl.utils.storage import load_shootings_database

    s3 = make_boto3_session(config=config).client("s3")
    gdf = load_shootings_database(s3=s3)
    incident_numbers = gdf["dc_key"].astype(str).unique().tolist()
    return [WorkItem(item_id=inc) for inc in incident_numbers]
