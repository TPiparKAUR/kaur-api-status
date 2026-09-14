import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import KESKKONNAAGENTUURI_SOURCES
from .downloader import DataDownloader
from .health import HealthChecker
from .sources import SOURCES_METADATA

app = typer.Typer(help="Keskkonnaagentuuri andmete allalaadija")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console)]
)
logger = logging.getLogger(__name__)

@app.command()
def download(
    source: Optional[str] = typer.Option(
        None,
        "--source",
        "-s",
        help="Andmeallika nimi (nt. kese, ilm, emo). Jäta tühjaks kõigi allalaadimiseks."
    )
) -> None:
    downloader = DataDownloader()

    if source:
        if source not in KESKKONNAAGENTUURI_SOURCES:
            console.print(f"[red]Tundmatu andmeallikas: {source}[/red]")
            console.print(f"Saadaolevad: {', '.join(KESKKONNAAGENTUURI_SOURCES.keys())}")
            raise typer.Exit(1)

        sources_to_download = {source: KESKKONNAAGENTUURI_SOURCES[source]}
    else:
        sources_to_download = KESKKONNAAGENTUURI_SOURCES

    console.print(f"[cyan]Laadime alla {len(sources_to_download)} andmeallikat...[/cyan]")

    results = {}
    for source_name, source_config in sources_to_download.items():
        console.print(f"\n[blue]{source_config.name}[/blue]: {source_config.description}")
        data = downloader.download(source_config)
        if data:
            path = downloader.process_and_save(source_name, data)
            if path:
                results[source_name] = path
                console.print(f"[green]✓ Salvestatud: {path}[/green]")
            else:
                console.print(f"[yellow]⊘ Andmed muutumata (checksum sama)[/yellow]")
        else:
            console.print(f"[red]✗ Allalaadimine ebaõnnestus[/red]")

    if results:
        console.print(f"\n[green]Edukas allalaadimine: {len(results)} andmeallikat[/green]")
    else:
        console.print(f"\n[yellow]Ühtegi uut andmest ei salvestatud[/yellow]")

@app.command()
def list_sources() -> None:
    console.print("[cyan]Keskkonnaagentuuri andmeallikad:[/cyan]\n")
    for name, config in KESKKONNAAGENTUURI_SOURCES.items():
        console.print(f"  [bold]{name}[/bold] - {config.name}")
        console.print(f"    {config.description}")
        console.print(f"    URL: {config.url}")
        console.print()

@app.command()
def health(source: Optional[str] = typer.Option(None, "--source", "-s", help="Konkreetse andmeallikate kontrollimine")) -> None:
    """Kontrolli andmeallikate kättesaadavust."""
    checker = HealthChecker()

    if source:
        if source not in KESKKONNAAGENTUURI_SOURCES:
            console.print(f"[red]Tundmatu andmeallikas: {source}[/red]")
            raise typer.Exit(1)
        results = [checker.check_endpoint(source)]
    else:
        console.print("[cyan]Kontrollime andmeallikate seisundit...[/cyan]\n")
        results = checker.check_all()

    table = Table(title="Andmeallikate seisund", show_header=True)
    table.add_column("Allikas", style="cyan")
    table.add_column("Nimi", style="magenta")
    table.add_column("Seisund", style="green")
    table.add_column("Aeg (ms)", style="yellow")

    for result in results:
        status = result["status"]
        status_style = "green" if status == "healthy" else "red"
        response_time = result.get("response_time_ms", "-")

        table.add_row(
            result["source"],
            result.get("name", "-")[:30],
            f"[{status_style}]{status}[/{status_style}]",
            str(response_time)
        )

    console.print(table)
    console.print()
    console.print("[cyan]Detailid:[/cyan]")
    for result in results:
        if result["status"] != "healthy":
            console.print(f"[red]{result['source']}[/red]: {result.get('error', 'Unknown error')}")

if __name__ == "__main__":
    app()
