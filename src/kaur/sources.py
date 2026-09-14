"""
Keskkonnaagentuuri andmeallikad ja nende metaandmed.

Andmeallikate nimekiri ja nende kontaktandmed.
"""

SOURCES_METADATA = {
    "kese": {
        "name": "Keskkonnateabe süsteemi avalik kuvand (KESE)",
        "organization": "Keskkonnaagentuuri",
        "url": "https://eelis.ee/eelis/middleware/xml/public",
        "format": "xml",
        "description": "Keskkonna alaseid teavet - vesi, õhk, heli, jäätmed",
        "contact": "https://www.keskkonnaagentuuri.ee/",
        "license": "CC0",
        "update_frequency": "varies",
    },
    "ilm": {
        "name": "Ilmateade (Eesti Meteoroloogia ja Hüdroökoloogia)",
        "organization": "Eesti Meteoroloogia ja Hüdroökoloogia Instituut",
        "url": "https://www.ilmateenistus.ee/xml/observations.php",
        "format": "xml",
        "description": "Jaam-põhised ilmaandmed ja jälgimistulemused",
        "contact": "https://www.ilmateenistus.ee/",
        "license": "CC BY 4.0",
        "update_frequency": "hourly",
    },
    "emo": {
        "name": "EMO REST API (meteoroloogilised andmed)",
        "organization": "Eesti Meteoroloogia ja Hüdroökoloogia Instituut",
        "url": "https://www.ilmateenistus.ee/weather/rest/",
        "format": "json",
        "description": "REST API meteoroloogiliste andmete jaoks",
        "contact": "https://www.ilmateenistus.ee/",
        "license": "CC BY 4.0",
        "update_frequency": "real-time",
    },
}

def get_source_info(source_code: str) -> dict | None:
    """Tagasta andmeallikate metaandmed."""
    return SOURCES_METADATA.get(source_code)

def list_all_sources() -> list[str]:
    """Loetelu kõigist saadaolevatest andmeallikatest."""
    return list(SOURCES_METADATA.keys())
