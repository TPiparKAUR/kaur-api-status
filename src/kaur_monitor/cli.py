"""Command line interface. Standard library argparse, no dependencies."""

from __future__ import annotations

import argparse
import functools
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import analysis, dashboard, discover, inventory, report, store
from .check import STATUS_UNKNOWN, CertCache, check_endpoint, looks_like_local_network_failure

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
        print(f"Dashboard: {dashboard.write([])}")
        return 0

    print(f"Kontrollin {len(entries)} otspunkti ({args.workers} lõime)...\n")
    # One TLS-expiry cache shared across the whole run: most endpoints sit
    # behind two hosts, so without it every endpoint would open its own extra
    # handshake just to read a certificate identical to its neighbour's.
    # retry=True: a failing endpoint is rechecked once a few seconds later
    # before the result is logged, so one dropped packet cannot by itself
    # become a recorded outage.
    run_check = functools.partial(check_endpoint, cert_cache=CertCache(), retry=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(run_check, entries))

    hosts = {e["id"]: urlsplit(str(e["url"])).hostname for e in entries}
    if looks_like_local_network_failure(records, hosts):
        print(
            "HOIATUS: iga otspunkt mitmel eri hostil ebaõnnestus enne vastust — "
            "tõenäoliselt on katkenud kontrollija enda võrguühendus, mitte teenused.\n"
            "Kirjed logitakse seisundiga TEADMATA ega mõjuta käideldavust.\n"
        )
        for record in records:
            record["status"] = STATUS_UNKNOWN

    _print_results(records)

    # Every endpoint was checked; grouped ones are recorded as one. A reader
    # wants to know whether EELIS answers, and the repository does not want 261
    # lines every half hour to say that it did.
    group_of = {e["id"]: str(e["group"]) for e in entries if e.get("group")}
    logged = analysis.collapse_groups(records, group_of)
    if group_of:
        print(f"\n{len(records)} kontrolli koondatud {len(logged)} kirjeks.")

    if not args.dry_run:
        log_path = store.append(logged)
        known = inventory.units(inventory.load_or_empty(config), inventory.load_groups(config))
        report_path = report.write(known)
        data_path = dashboard.write(known)
        print(f"\nLogitud:   {log_path}\nRaport:    {report_path}\nDashboard: {data_path}")
    else:
        print("\n(--dry-run: midagi ei kirjutatud)")

    failed = sum(1 for r in records if r["status"] in ("down", "degraded"))
    print(f"\nKokku: {len(records)} kontrollitud, {failed} probleemiga.")
    return 1 if (failed and args.fail_on_down) else 0


def cmd_report(args: argparse.Namespace) -> int:
    """Rebuild both rendered views of the log: the Markdown report and the page data."""
    config = Path(args.config)
    known = inventory.units(inventory.load_or_empty(config), inventory.load_groups(config))
    print(f"Raport kirjutatud:    {report.write(known)}")
    print(f"Dashboard kirjutatud: {dashboard.write(known)}")
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


def _parse_headers(pairs: list[str] | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--header ootab kuju 'Nimi=väärtus', sain {pair!r}")
        headers[key.strip()] = value.strip()
    return headers


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        headers = _parse_headers(args.header)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    root = args.openapi
    if args.from_inventory:
        # Reuse an entry already in the inventory rather than repeating the
        # service address as an argument. The root endpoint of a PostgREST
        # service is both the thing we monitor and the thing that lists its
        # tables, so it already carries the URL and the headers discovery needs.
        known = {e["id"]: e for e in inventory.load_or_empty(Path(args.config))}
        entry = known.get(args.from_inventory)
        if entry is None:
            print(
                f"Inventaris pole otspunkti {args.from_inventory!r}. "
                f"Saadaval: {', '.join(sorted(known)) or '(tühi)'}",
                file=sys.stderr,
            )
            return 2
        root = str(entry["url"]).split("?")[0]
        headers = {**dict(entry.get("headers") or {}), **headers}
        print(f"Avastan otspunkti {args.from_inventory!r} põhjal: {root}")

    try:
        if root:
            found = discover.from_openapi(
                root,
                extra_headers=headers or None,
                table_prefix=args.table_prefix,
                row_limit=args.row_limit,
            )
        else:
            found = discover.from_ckan(args.ckan, query=args.query, rows=args.rows)
    except discover.DiscoveryError as exc:
        print(f"Avastamine ebaõnnestus: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        systems: dict[str, int] = {}
        for entry in found:
            systems[str(entry.get("system") or "-")] = systems.get(str(entry.get("system")), 0) + 1
        print(f"Leitud {len(found)} otspunkti. Süsteemide kaupa:")
        for system, count in sorted(systems.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>4}  {system}")
        print("\nEsimesed 40:")
        for entry in found[:40]:
            print(f"  {entry['id']:<44} {entry['url']}")
        if len(found) > 40:
            print(f"  … ja veel {len(found) - 40}")
        print("\n(--dry-run: inventari ei muudetud)")
        return 0

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

    rep = sub.add_parser("report", help="koosta REPORT.md ja dashboardi andmed logist")
    rep.set_defaults(func=cmd_report)

    lst = sub.add_parser("list", help="näita inventari")
    lst.set_defaults(func=cmd_list)

    val = sub.add_parser("validate", help="kontrolli inventari süntaksit")
    val.set_defaults(func=cmd_validate)

    disc = sub.add_parser("discover", help="avasta otspunktid kataloogist või OpenAPI kirjeldusest")
    source = disc.add_mutually_exclusive_group(required=True)
    source.add_argument("--openapi", help="PostgREST-i juur-URL, mis annab OpenAPI kirjelduse")
    source.add_argument("--ckan", help="CKAN-tüüpi kataloogi baas-URL")
    source.add_argument(
        "--from-inventory",
        metavar="ID",
        help="võta teenuse juur ja päised olemasolevast inventari kirjest",
    )
    disc.add_argument(
        "--header",
        action="append",
        metavar="NIMI=VÄÄRTUS",
        help="päis avastuspäringule ja kõigile leitud kirjetele, korduv",
    )
    disc.add_argument("--table-prefix", default="f_", help="ainult selle eesliitega tabelid")
    disc.add_argument("--row-limit", type=int, default=1, help="limit leitud päringutes")
    disc.add_argument("--query", default="", help="CKAN: otsingupäring")
    disc.add_argument("--rows", type=int, default=1000, help="CKAN: maks andmestike arv")
    disc.add_argument("--dry-run", action="store_true", help="näita leitut, ära muuda inventari")
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
