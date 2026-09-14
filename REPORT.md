# Keskkonnaagentuuri API-de seisundiraport

Koostatud: **2026-09-14 16:43** (EET/EEST) · jälgitavaid otspunkte: **18** · kontrollikirjeid logis: **36**

Hetkeseis — KORRAS: **18**

## Praegune seis

| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |
|---|---|---|---|---|---|
| `eelis-rahvalad`<br><sub>EELIS rahvusvahelised alad, Kurese loodusala</sub> | **KORRAS** | 200 · 1191 ms | - | 2026-09-14 16:43 |  |
| `eelis-rahvalad-dok`<br><sub>EELIS rahvusvaheliste alade dokumendid, seosetabel</sub> | **KORRAS** | 200 · 1201 ms | - | 2026-09-14 16:43 |  |
| `eelis-rahvalad-linnuala`<br><sub>EELIS linnuala määramise õiguslik alus (pesastatud filter)</sub> | **KORRAS** | 200 · 1146 ms | - | 2026-09-14 16:43 |  |
| `eelis-rahvalad-seosed`<br><sub>EELIS rahvusvahelised alad koos dokumentidega (embedding)</sub> | **KORRAS** | 200 · 1157 ms | - | 2026-09-14 16:43 |  |
| `hydroseire`<br><sub>Hüdroloogiline seire, veetase 2023-01-02</sub> | **KORRAS** | 200 · 1217 ms | - | 2026-09-14 16:43 |  |
| `kaia-items-query`<br><sub>KAIA dokumentide metaandmete päring</sub> | **KORRAS** | 200 · 1246 ms | - | 2026-09-14 16:43 |  |
| `kaia-lists-active`<br><sub>KAIA aktiivse valikuhierarhia metaandmed</sub> | **KORRAS** | 200 · 1280 ms | - | 2026-09-14 16:43 |  |
| `kaia-lists-archive`<br><sub>KAIA arhiivi valikuhierarhia metaandmed</sub> | **KORRAS** | 200 · 1451 ms | - | 2026-09-14 16:43 |  |
| `kaia-swagger`<br><sub>KAIA OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 1608 ms | - | 2026-09-14 16:43 |  |
| `keskkonnaandmed-root`<br><sub>Juur-URL, OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 2391 ms | - | 2026-09-14 16:43 | body truncated at 65536 bytes, parse skipped |
| `keskkonnaseire`<br><sub>Keskkonnaseire, programm PR0127 aastal 2021</sub> | **KORRAS** | 200 · 1471 ms | - | 2026-09-14 16:43 |  |
| `kliima-element`<br><sub>Kliima elementide metaandmed</sub> | **KORRAS** | 200 · 1910 ms | - | 2026-09-14 16:43 |  |
| `kliima-jaam-vaatlus`<br><sub>Kliima vaatlusjaamade metaandmed</sub> | **KORRAS** | 200 · 1911 ms | - | 2026-09-14 16:43 |  |
| `kliima-kuu`<br><sub>Kliima kuu andmed</sub> | **KORRAS** | 200 · 1944 ms | - | 2026-09-14 16:43 |  |
| `kliima-minut`<br><sub>Kliima 10-minuti andmed</sub> | **KORRAS** | 200 · 1943 ms | - | 2026-09-14 16:43 |  |
| `kliima-paev`<br><sub>Kliima ööpäeva andmed, Ruhnu ja Kihnu õhuniiskus 2023</sub> | **KORRAS** | 200 · 1915 ms | - | 2026-09-14 16:43 |  |
| `kliima-paev-nimefilter`<br><sub>Kliima ööpäeva andmed, Võru 2006 (like-filter ja sortimine)</sub> | **KORRAS** | 200 · 1880 ms | - | 2026-09-14 16:43 |  |
| `kliima-tund`<br><sub>Kliima tunniandmed</sub> | **KORRAS** | 200 · 1943 ms | - | 2026-09-14 16:43 |  |

## Käideldavus

| Otspunkt | 24 h | 7 päeva | 30 päeva |
|---|---|---|---|
| `eelis-rahvalad` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `eelis-rahvalad-dok` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `eelis-rahvalad-linnuala` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `eelis-rahvalad-seosed` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `hydroseire` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kaia-items-query` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kaia-lists-active` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kaia-lists-archive` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kaia-swagger` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `keskkonnaandmed-root` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `keskkonnaseire` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-element` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-jaam-vaatlus` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-kuu` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-minut` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-paev` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-paev-nimefilter` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |
| `kliima-tund` | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> | 100.0 % <sub>(n=2)</sub> |

## Katkestused

Logitud perioodil katkestusi ei ole.

---

Ajad on EET/EEST vööndis. Logi hoiab UTC ISO 8601 kujul kaustas `logs/`.
Seisund **TEADMATA** tähendab, et kontrollija ise ei saanud võrku — see ei lähe käideldavuse arvestusse.
