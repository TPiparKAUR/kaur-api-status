# KAUR allalaadimine

Keskkonnaagentuuri avalike API-de andmete automaatne allalaadimine, töötlemine ja versioonimine.

## Ülevaade

Lahendus laeb alla Keskkonnaagentuuri ja seotud avalike andmebaasidest andmeid, salvestab need Parquet formaadis ning versioone need Gitis. Iga muutus loob automaatselt committi metaandmetega (checksum, timestamp).

## Iseärasused

- ✅ **Inkrementaalne** - ainult muutunud andmeid salvestatakse (SHA256 checksum)
- ✅ **Automatiseeritud** - GitHub Actions ajastatud käivitused
- ✅ **Käsitsi käivitav** - `manual run` GitHub Actions
- ✅ **Parquet** - tõhus binaarformaat andmetega
- ✅ **Laiendatav** - uute andmeallikate lisamine lihtne
- ✅ **Auditeeritav** - täielik git ajalugu iga muutusega

## Kiire alustamine

### Käsitsi allalaadimine

```bash
# Paigaldus
pip install -r requirements.txt

# Kõik andmeallikad
python main.py download

# Konkreetne allikas
python main.py download --source kese

# Saadaolevad allikad
python main.py list-sources
```

### Makefile käsud

```bash
make install          # Sõltuvused
make download         # Allalaadimine
make list            # Andmeallikad
make lint            # Koodi kontroll
make test            # Testid
make clean           # Puhastus
```

## Automaatne allalaadimine

GitHub Actions töövoog käivitub:
1. **Ajastatud**: Nädala esmaspäeval kell 06:00 UTC
2. **Käsitsi**: GitHub Actions interface'st (manual trigger)

Iga käivitus:
- Laeb andmed alla
- Kontrolliseerib muutusi (checksum)
- Teeb `git commit` kui andmed muutunud
- Tõukab repo-sse

## Struktuur

```
.
├── src/kaur/
│   ├── config.py          # Andmeallikate deklaratsioon
│   ├── downloader.py      # Allalaadimise loogika
│   ├── cli.py             # Käsureainterfeis (Typer)
│   └── __init__.py
├── tests/                  # Ühik-testid
├── data/                   # Andmefailid (Parquet)
├── .github/workflows/      # GitHub Actions
├── main.py                # Sisenemine
├── pyproject.toml         # Python projekt
├── requirements.txt       # pip sõltuvused
├── CLAUDE.md             # Tehniline dokumentatsioon
└── Makefile              # Valikud
```

## Andmefailid ja metaandmed

### Andmed
- Asukoht: `data/{allikas}.parquet`
- Formaat: Apache Parquet (tihendatud, kolonnaalne)

### Metaandmed
- Asukoht: `data/.metadata/{allikas}.json`
- Sisaldus:
  ```json
  {
    "checksum": "sha256...",
    "timestamp": "2024-01-15T12:34:56Z",
    "version": "1.0",
    "rows": 1234
  }
  ```

## Andmeallikad

| Allikas | Nimi | Kirjeldus |
|---------|------|-----------|
| `kese` | KESE | Keskkonnateabe süsteemi avalik kuvand |
| `ilm` | Ilmateade | Eesti Meteoroloogia - ilmaandmed (XML) |
| `emo` | EMO | Meteoroloogilised andmed REST API |

## Uue andmeallikaga liitmine

1. **Konfigureeri** (`src/kaur/config.py`):
```python
"uus_allikas": DataSourceConfig(
    name="Nimi",
    url="https://api.example.com/data",
    format="json",  # või "xml"
    description="Kirjeldus"
)
```

2. **Töötlemine** (`src/kaur/downloader.py`):
   - JSON: juba toetatud
   - XML: juba toetatud
   - Custom: täienda `_process_*` meetodit

3. **Testi**:
```bash
python main.py download --source uus_allikas
```

## Versioonihaldus

Git track'ib:
- ✅ Kood (Python, YAML, etc)
- ✅ Metaandmed (JSON)
- ✅ Andmefailid (Parquet) - ainult muutused

Iga muutus genereerib committi kujul:
```
chore: Keskkonnaagentuuri andmete allalaadimine

Andmefailid: parquet
Metaandmed: checksum, timestamp, versioon
```

## Metoodoloogia

- **Inkrementaalne**: Checksum võrdlemine - sama andmed = ei commit
- **Idempotentne**: Korduvad käivitused ohutud
- **Audit trail**: Git ajalugu näitab kõiki muutusi
- **Reproducible**: Parquet formaat universaalus ja stabiilne

## Tehniline teabeleht

Vaata [CLAUDE.md](./CLAUDE.md) arhitektuuri üksikasjade jaoks.

## Litsents

MIT License - vt. [LICENSE](./LICENSE)
