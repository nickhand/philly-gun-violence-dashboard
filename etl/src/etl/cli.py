import typer

from etl.boundaries.cli import app as boundaries_app
from etl.courts.cli import app as courts_app
from etl.homicides.cli import app as homicides_app
from etl.shootings.cli import app as shootings_app
from etl.streets.cli import app as streets_app

app = typer.Typer(help="ETL CLI for the Philadelphia Gun Violence Dashboard")
app.add_typer(boundaries_app, name="boundaries")
app.add_typer(courts_app, name="courts")
app.add_typer(homicides_app, name="homicides")
app.add_typer(shootings_app, name="shootings")
app.add_typer(streets_app, name="streets")


@app.callback()
def main() -> None:
    """ETL CLI for the Philadelphia Gun Violence Dashboard."""
    pass


if __name__ == "__main__":
    app()
