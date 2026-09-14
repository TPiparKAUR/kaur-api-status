# KAUR allalaadimine

Keskkonnaagentuuri avalike API-de andmete automaatne allalaadimine ja arhiveerimine.

## Arhitektuur

- **Python 3.12** - uv package manager
- **Polars + PyArrow** - andmete töötlus ja Parquet salvestamine
- **GitHub Actions** - ajastatud allalaadimised
- **Metaandmed** - JSON checksum ja timestamp metadata

## Andmeallikad

```
kese    - Keskkonnateabe süsteemi avalik kuvand
ilm     - Eesti Meteoroloogia ja Hüdroökoloogia - ilmaandmed
emo     - EMO REST API
```

## Kasutamine

### Käsitsi allalaadimine

```bash
# Kõik andmeallikad
uv run python main.py download

# Konkreetne allikas
uv run python main.py download --source kese

# Saadaolevate allikate nimekiri
uv run python main.py list-sources
```

### Automaatne allalaadimine

GitHub Actions töövoog käivitub:
- Nädala esimesel päeval kell 6:00 UTC
- Käsitsi GitHub Actions interface'st

## Andmete versioonimine

- **Parquet failid**: `data/{allikas}.parquet`
- **Metaandmed**: `data/.metadata/{allikas}.json`
  - `checksum` - SHA256 andmete kontrollsumma
  - `timestamp` - allalaadimise aeg (UTC ISO 8601)
  - `rows` - ridade arv

Ainult muutunud andmed genereerivad git committi.

## Struktuuri

```
src/kaur/
├── __init__.py
├── config.py          # Andmeallikate konfiguratsioon
├── downloader.py      # Allalaadimise ja töötlemise loogika
└── cli.py             # Käsureainterfeis

main.py              # Sisenemine
pyproject.toml       # Projekti konfiguratsiooon
.github/workflows/   # GitHub Actions tööd
```

## Laienemine

Uue andmeallikaga:

1. Lisa `KESKKONNAAGENTUURI_SOURCES` konfi (`config.py`)
2. Täienda `_process_json()` või `_process_xml()` (`downloader.py`)
3. Käivita: `uv run python main.py download --source <nimi>`

## Metoodoloogia

- **Inkrementaalne** - sama checksum = ei salvestata
- **Idempotentne** - korduvad käivitused ohutud
- **Tõstetav** - uute API-de lisamine triviaalne
- **Audit trail** - git commit iga muutuse kohta
