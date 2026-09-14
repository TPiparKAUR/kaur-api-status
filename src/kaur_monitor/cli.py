"""Command line interface. Standard library argparse, no dependencies."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import discover, inventory, report, store
from .check import STATUS_UNKNOWN, check_endpoint, looks_like_local_network_failure

_MARK = {"ok": "  OK  ", "degraded": "HÄIRE ", "down": " MAAS ", "unknown": "  ??  "}


def _print_results(records: list[dict[str, Any]]) -> None:
    width = max((len(r["id"]) for r in records), default=10)
    for record in sorted(records, key=lambda r: (r["status"] != "ok", r["id"])):
        ms = f"{record['ms']} ms" if record.get("ms") is not None else "-"
        detail = f"  {record['detail']}" if record.get("detail") else ""
        print(f"[{_MARK.get(record['status'], '  ??  ')}] {record['id']:<{width}}  {ms:>8}{detail}")


def cmd_check(args: argparse.Namespace) -> int:
    config = Path(args.config)
    entries = inventory.enabled_only(inventory.load_or_empty(config))
    if not entries:
        print(
            f"Inventar on tühi ({config}) — kontrollida pole midagi.\n"
            f"Lisa otspunkte: python monitor.py import-urls urls.txt"
        )
        # Still refresh the report so it carries today's date and states plainly
        # that nothing is being monitored yet.
        print(f"Raport: {report.write([])}")
        return 0

    print(f"Kontrollin {len(entries)} otspunkti ({args.workers} lõime)...\n")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(check_endpoint, entries))

    if looks_like_local_network_failure(records):
        print(
            "HOIATUS: iga otspunkt ebaõnnestus enne vastust — tõenäoliselt on "
            "katkenud kontrollija enda võrguühendus, mitte teenused.\n"
            "Kirjed logitakse seisundiga TEADMATA ega mõjuta käideldavust.\n"
        )
        for record in records:
            record["status"] = STATUS_UNKNOWN

    _print_results(records)

    if not args.dry_run:
        log_path = store.append(records)
        report_path = report.write(inventory.load_or_empty(config))
        print(f"\nLogitud: {log_path}\nRaport:  {report_path}")
    else:
        print("\n(--dry-run: midagi ei kirjutatud)")

    failed = sum(1 for r in records if r["status"] in ("down", "degraded"))
    print(f"\nKokku: {len(records)} kontrollitud, {failed} probleemiga.")
    return 1 if (failed and args.fail_on_down) else 0


def cmd_report(args: argparse.Namespace) -> int:
    path = report.write(inventory.load_or_empty(Path(args.config)))
    print(f"Raport kirjutatud: {path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    entries = inventory.load(Path(args.config))
    for entry in sorted(entries, key=lambda e: e["id"]):
        flags = []
        if not entry.get("enabled", True):
            flags.append("välja lülitatud")
        if not entry.get("verified", False):
            flags.append("KONTROLLIMATA")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{entry['id']:<44} {entry['url']}{suffix}")
    print(f"\n{len(entries)} otspunkti.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    entries = inventory.load(Path(args.config))
    unverified = sum(1 for e in entries if not e.get("verified", False))
    print(f"Inventar on korrektne: {len(entries)} otspunkti, {unverified} kontrollimata.")
    return 0


def _merge_and_save(found: list[dict[str, Any]], config: Path) -> int:
    existing = inventory.load(config) if config.exists() else []
    merged, added, skipped = inventory.merge(existing, found)
    inventory.save(merged, config)
    print(f"Leitud {len(found)}; lisatud {added} uut, {skipped} oli juba olemas.")
    print(f"Inventar: {config} ({len(merged)} otspunkti)")
    if added:
        print("\nKõik uued kirjed on 'verified = false'. Vaata URL-id üle ja märgi õiged.")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        found = discover.from_ckan(args.ckan, query=args.query, rows=args.rows)
    except discover.DiscoveryError as exc:
        print(f"Avastamine ebaõnnestus: {exc}", file=sys.stderr)
        return 2
    return _merge_and_save(found, Path(args.config))


def cmd_import_urls(args: argparse.Namespace) -> int:
    try:
        found = discover.from_urls(Path(args.file))
    except discover.DiscoveryError as exc:
        print(f"Import ebaõnnestus: {exc}", file=sys.stderr)
        return 2
    return _merge_and_save(found, Path(args.config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitor.py",
        description="Keskkonnaagentuuri API-de kättesaadavuse jälgija.",
    )
    parser.add_argument(
        "--config", default=str(inventory.CONFIG_PATH), help="otspunktide inventar (TOML)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="kontrolli kõiki otspunkte ja uuenda raport")
    check.add_argument("--workers", type=int, default=8, help="paralleelsete kontrollide arv")
    check.add_argument("--dry-run", action="store_true", help="ära kirjuta logi ega raportit")
    check.add_argument(
        "--fail-on-down", action="store_true", help="lõpeta veakoodiga, kui midagi on maas"
    )
    check.set_defaults(func=cmd_check)

    rep = sub.add_parser("report", help="koosta REPORT.md olemasolevast logist")
    rep.set_defaults(func=cmd_report)

    lst = sub.add_parser("list", help="näita inventari")
    lst.set_defaults(func=cmd_list)

    val = sub.add_parser("validate", help="kontrolli inventari süntaksit")
    val.set_defaults(func=cmd_validate)

    disc = sub.add_parser("discover", help="avasta otspunktid CKAN-tüüpi kataloogist")
    disc.add_argument("--ckan", required=True, help="kataloogi baas-URL")
    disc.add_argument("--query", default="", help="otsingupäring")
    disc.add_argument("--rows", type=int, default=1000, help="maksimaalne andmestike arv")
    disc.set_defaults(func=cmd_discover)

    imp = sub.add_parser("import-urls", help="impordi otspunktid tekstifailist (üks URL reas)")
    imp.add_argument("file", help="tekstifail URL-idega")
    imp.set_defaults(func=cmd_import_urls)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except inventory.InventoryError as exc:
        print(f"Inventari viga: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
