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
| `monitor.yml` | iga 30 min + käsitsi + `config/**` muudatusel | kontrollib, logib, uuendab raporti ja lehe, teavitab |
| `discover.yml` | ainult käsitsi | avastab teenuse otspunktid selle enda kirjeldusest |
| `tests.yml` | iga push | testid + inventari süntaks |

30-minutiline sagedus on 1 440 jooksu kuus. Mõõdetud jooks 283 otspunktiga
kestab 43 sekundit, seega arvestatakse üks minut jooksu kohta — kokku 1 440
minutit, mis mahub 2 000-minutilisse tasuta kvooti. Varu on siiski õhuke:
kui jooks ületab minuti, arvestatakse kaks ja kuu maht on 2 880. Otspunkte
lisades tasub jooksu kestust jälgida.

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

## Avalik seisundileht (GitHub Pages)

Kaustas `docs/` on staatiline leht, mis näitab sama infot inimloetaval kujul:
hetkeseis, teenuste kirjeldused, kättesaadavuse ja vastuseaja graafikud ning
katkestuste logi. Leht on eestikeelne ja mõeldud lugejale, kes API-dega iga
päev ei tegele.

### Kuidas see töötab

```
logs/*.jsonl                 ← seire kirjutab, üks rida kontrolli kohta
      │
      │  monitor.py check  (või  report)
      ▼
docs/data/status.json        ← koondatud: hetkeseis, päevastatistika, katkestused
      │
      │  brauser laeb ühe faili
      ▼
docs/index.html + app.js     ← joonistab tahvli ja graafikud
```

Kogu arvutus käib jooksu ajal Pythonis. Brauser saab ühe ~100 KB faili, mitte
kogu logi. Leht ei pöördu ühegi välise teenuse poole — ka Chart.js on repos
kaustas `docs/vendor/`.

Kui logis on liiga vähe ajalugu, ei joonista leht graafikut, vaid ütleb seda
otse. Näidisandmeid ei genereerita kunagi.

### Lehe sisselülitamine

GitHubis: **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`**.

Pärast seda on leht aadressil:

```
https://tpiparkaur.github.io/kaur-api-status/
```

> **NB!** GitHub Pages ei serveeri privaatset repot tasuta plaanil. Leht ilmub
> alles siis, kui repo on avalik (või plaan tasuline).

## Enne avalikuks tegemist

Kontroll-loend. Esimesed kolm on üle vaadatud 2026-09-14 seisuga.

- [x] **Logis ei ole tundlikku sisu.** 1 263 kirjet skannitud: ei leitud
      autoriseerimispäiseid, API-võtmeid, tokeneid, isikukoode, e-posti
      aadresse, JWT-sid ega sisevõrgu hoste. Logikirje väljad on ainult
      `ts, id, status, stage, http, ms, bytes, sha256, cert_days, age_s,
      detail, members, ok`.
- [x] **Koodis ei ole saladusi.** GitHubi teavituste token tuleb jooksu ajal
      `${{ github.token }}`-ist ega satu kunagi repos olevasse faili.
- [x] **Litsents on olemas** — MIT, vt `LICENSE`.
- [ ] **Repo kirjeldus GitHubis** on veel vana („Laeb alla KAUR-i andmed
      arhiveerimiseks") — see ei kirjelda enam projekti.
- [ ] **Ümbernimetamine ja nähtavus** Settings-i alt.
- [ ] Pärast ümbernimetamist kohalikus koopias:
      `git remote set-url origin https://github.com/TPiparKAUR/kaur-api-status`

Repo ümbernimetamine ei nõua koodimuudatust: projektis ei ole ühtegi viidet
oma repo nimele. Vanad lingid suunatakse GitHubis automaatselt ümber.

### Teenuste kirjeldused

Lehel kuvatavad kirjeldused on failis `config/systems.toml`, mitte koodis.
Süsteemi nimi seal peab kattuma inventari `system` väljaga. Kirjelduseta
süsteem kuvatakse ilma tekstita.

## Rühmad: palju otspunkte, üks rida

EELIS avaldab 261 tabelit ühe teenuse taga. Juhtkonnale on oluline, kas EELIS
vastab, mitte milline 261-st — ja 261 logirida iga poole tunni tagant oleks
umbes gigabait committitud teksti aastas.

Rühm lahendab mõlemad. **Kõiki otspunkte kontrollitakse endiselt igal jooksul**,
aga logisse, raportisse ja lehele läheb üks kirje:

- kasvõi üks tabel ei vasta → **rühm on maas**, ja kirje nimetab, millised
- kõik vastavad → rühm on korras
- kirje hoiab ka loendurid (`258/261`), nii et käideldavuse protsent jääb õigeks

Mahuvõit: 283 üksuse asemel 23 → **84 MB aastas 1 GB asemel**.

Rühma määramine:

```toml
[[group]]
id = "eelis"
name = "EELIS andmestikud"
system = "EELIS"
verified = true

[[endpoint]]
id = "f-alad"
group = "eelis"      # <- viide rühmale
...
```

## Uue API lisamine jälgimisele

Kolm sammu, ainult andmefailides — koodi muuta pole vaja.

**1. Lisa otspunkt** faili `config/endpoints.toml`:

```toml
[[endpoint]]
id = "minu-teenus"                  # unikaalne lühinimi
name = "Minu teenuse lühikirjeldus" # kuvatakse tahvlil
system = "Kliima"                   # rühmitab lehel; vt config/systems.toml
url = "https://..."
expect = "json"                     # json | xml | any
headers = { "Accept" = "application/json" }
verified = true                     # alles siis, kui oled URL-i üle vaadanud
```

**2. Kontrolli, et fail on korrektne:**

```bash
python3 monitor.py validate
python3 monitor.py check          # kontrollib kohe ja uuendab lehe andmed
```

**3. Commiti.** Töövoog `monitor.yml` käivitub `config/**` muudatusel kohe,
nii et uus otspunkt saab esimese kontrolli ilma järgmist tsüklit ootamata.

Kui teenus on PostgREST-i tüüpi ja avaldab OpenAPI kirjelduse, saab kõik selle
tabelid korraga lisada — Actionsis **Discover endpoints → from_inventory** ja
sinna olemasoleva juurotspunkti id. Nii lisandus 261 EELIS-e otspunkti.

Uued avastatud kirjed on alati `verified = false`: need on lehel ja raportis
näha, aga ei ava GitHubi Issue't, sest vale päring ei ole teenuse katkestus.

### Väljad, mida tasub teada

| Väli | Milleks |
|---|---|
| `method` + `body` | kui lugemispäring käib POST-iga (nt KAIA dokumendiotsing) |
| `max_bytes` | piirab lugemist, kui vastus on suur |
| `timeout_s` | vaikimisi 30 s |
| `freshness_regex` + `max_age_s` | märgib HÄIRE-ks, kui andmed on seisma jäänud |
| `enabled = false` | jätab otspunkti ajutiselt vahele |

Kirjutavad meetodid (`PUT`, `PATCH`, `DELETE`) on keelatud — inventar keeldub
neist juba valideerimisel.

## Käsud

```
python3 monitor.py check              # kontrolli, logi, uuenda raport ja leht
python3 monitor.py check --dry-run    # kontrolli, ära kirjuta midagi
python3 monitor.py report             # koosta raport ja lehe andmed logist
python3 monitor.py list               # näita inventari
python3 monitor.py validate           # kontrolli inventari süntaksit
python3 monitor.py import-urls FAIL   # impordi URL-id tekstifailist
python3 monitor.py discover --ckan U  # avasta kataloogist
```

Testid: `python3 -m unittest discover -s tests`

---

## Litsents

MIT — vaata [LICENSE](./LICENSE).
