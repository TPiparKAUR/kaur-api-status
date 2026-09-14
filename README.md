# Keskkonnaagentuuri API-de seire

Kontrollib Keskkonnaagentuuri avalikke API-sid, peab arvet selle üle, **millal
ja kui kaua** iga teenus maas on olnud, ning koostab sellest raporti. Teenuse
kukkumisel avaneb GitHubi Issue ja taastumisel sulgub.

Töötab **ainult Pythoni standardteegiga**. Ei ole `pip install`-i, virtuaal‑
keskkonda ega väliseid teenuseid.

```bash
python3 monitor.py check
```

---

## Kiire alustamine

Kolm sammu, umbes kaks minutit.

**1. Pane URL-id faili**, üks reas. Silt pärast tühikut on vabatahtlik.

```
# urls.txt
https://example.org/geoserver/wfs?service=WFS&request=GetCapabilities   EELIS WFS
https://example.org/observations.php                                     Vaatlusandmed
```

**2. Impordi**

```bash
python3 monitor.py import-urls urls.txt
```

**3. Kontrolli**

```bash
python3 monitor.py check
```

Tulemus tuleb ekraanile, logitakse `logs/` kausta ja raport kirjutatakse
faili `REPORT.md`.

Kui otspunktid on kataloogis (CKAN-tüüpi avaandmete portaal), saab need
importimise asemel avastada:

```bash
python3 monitor.py discover --ckan https://<portaali-aadress> --query Keskkonnaagentuur
```

---

## Mida tähendab „töötab“

HTTP 200 **ei tähenda**, et teenus on korras. WFS võib vastata koodiga 200 ja
kehas olla `ows:ExceptionReport`. Ilmateenistuse API võib vastata koodiga 200
ja anda andmeid, mis lakkasid uuenemast kaks päeva tagasi. Kumbki ei ole
tavalise seirerakenduse jaoks nähtav.

Iga otspunkt läbib seepärast järjestatud etapid ja logitakse see, kui kaugele
ta jõudis:

| Etapp | Kontrollib |
|---|---|
| `dns` | nimi laheneb |
| `connect` | TCP + TLS ühendus, sertifikaadi aegumine |
| `http` | vastuse staatuskood |
| `content_type` | päis vastab oodatule |
| `parse` | keha on valiidne XML/JSON |
| `service_exception` | keha **ei ole** OGC veateade |
| `freshness` | uusim ajatempel kehas ei ole liiga vana |

Seisundeid on neli:

- **KORRAS** — kõik seadistatud etapid läbitud
- **HÄIRE** — teenus vastab, aga sisu on vigane või seisev
- **MAAS** — ei vasta, või vastab veateatega
- **TEADMATA** — *meie* kontrollija ei saanud võrku

**TEADMATA** on oluline. Kui kõik otspunktid ebaõnnestuvad enne vastuse
saamist, on tõenäoliselt katki kontrollija enda võrk, mitte kõik Eesti
teenused korraga. Sellised kirjed jäetakse käideldavuse arvestusest välja, et
runneri tõrge ei näiks katkestusena.

---

## Raport

`REPORT.md` genereeritakse iga kontrolli järel ja sisaldab:

- **Praegune seis** — iga otspunkti seisund, vastuseaeg, andmete vanus
- **Käideldavus** — protsent 24 h, 7 ja 30 päeva kohta
- **Katkestused** — millal algas, millal lõppes, kui kaua kestis, miks
- **Hoiatused** — aeguvad TLS-sertifikaadid, kontrollimata URL-id

Ajad on raportis Eesti aja järgi (EET/EEST), logis UTC ISO 8601 kujul.

---

## Teavitused

Teenuse kukkumisel avab töövoog GitHubi Issue sildiga `api-incident` ja
taastumisel kommenteerib ning sulgeb selle. Repo jälgijad saavad e-kirja
automaatselt — SMTP-d ega saladusi ei ole vaja seadistada.

Seisund **TEADMATA** ei ava kunagi Issue't.

---

## Automaatika

| Töövoog | Millal | Mida teeb |
|---|---|---|
| `monitor.yml` | iga tund + käsitsi | kontrollib, logib, commitib, teavitab |
| `discover.yml` | ainult käsitsi | avastab otspunktid kataloogist |
| `tests.yml` | iga push | testid + inventari süntaks |

Tunnine sagedus on ~730 jooksu kuus, mis mahub tasuta privaatse repo limiiti.
Avalikul repol on Actions piiramatu — seal võib sagedust tõsta.

---

## Inventar

`config/endpoints.toml`. Otspunktid on **andmed, mitte kood** — koodis ei ole
ühtegi URL-i.

```toml
[[endpoint]]
id = "eelis-wfs"
name = "EELIS WFS GetCapabilities"
system = "EELIS"
url = "https://..."
expect = "xml"              # json | xml | any
freshness_regex = '"ts":"([^"]+)"'
max_age_s = 3600
verified = true
```

Täielik väljade loend: `config/endpoints.example.toml`.

### `verified`

Iga kirje algab väärtusega `verified = false` ja raport märgib sellised eraldi
ära. Lipu tõstab **inimene**, kui on veendunud, et URL on õige. Avastamine ega
importimine ei märgi kunagi midagi kontrollituks.

Käsitsi parandatud kirjet ei kirjutata uuel avastamisel üle.

---

## Praegune piirang

**Inventar on tühi.** Selle repo autoril ei olnud ligipääsu Eesti riigi
süsteemidele — puhverserver vastas kõigile `.ee` domeenidele `403 policy
denial` — mistõttu ühtegi otspunkti ei ole kontrollitud ega koodi kirjutatud.
Vale URL oleks halvem kui puuduv URL.

Nimekirja täitmiseks vaata:

- **avaandmed.eesti.ee** — filtreeri avaldaja järgi
- **RIHA** (riha.eesti.ee) — riigi infosüsteemide ametlik register
- **keskkonnaportaal.ee**
- KAUR-i INSPIRE/OGC teenuste metaandmed (WMS/WFS `GetCapabilities`)

Otsi otspunkte nende süsteemide juurest: KESE (keskkonnaseire), EELIS (looduse
infosüsteem), Metsaregister, Riigi Ilmateenistus, Keskkonnaportaal.

---

## Käsud

```
python3 monitor.py check              # kontrolli, logi, uuenda raport
python3 monitor.py check --dry-run    # kontrolli, ära kirjuta midagi
python3 monitor.py report             # koosta raport logist
python3 monitor.py list               # näita inventari
python3 monitor.py validate           # kontrolli inventari süntaksit
python3 monitor.py import-urls FAIL   # impordi URL-id tekstifailist
python3 monitor.py discover --ckan U  # avasta kataloogist
```

Testid: `python3 -m unittest discover -s tests`

---

## Litsents

MIT — vaata [LICENSE](./LICENSE).
