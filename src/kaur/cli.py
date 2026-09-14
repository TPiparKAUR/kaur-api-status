import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from .config import KESKKONNAAGENTUURI_SOURCES
from .downloader import DataDownloader

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

if __name__ == "__main__":
    app()
