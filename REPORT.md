# Keskkonnaagentuuri API-de seisundiraport

Koostatud: **2026-09-14 15:40** (EET/EEST) · jälgitavaid otspunkte: **14** · kontrollikirjeid logis: **84**

Hetkeseis — KORRAS: **14**

## Praegune seis

| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |
|---|---|---|---|---|---|
| `eelis-rahvalad`<br><sub>EELIS rahvusvahelised alad, Kurese loodusala</sub> | **KORRAS** | 200 · 1294 ms | - | 2026-09-14 15:40 |  |
| `eelis-rahvalad-dok`<br><sub>EELIS rahvusvaheliste alade dokumendid, seosetabel</sub> | **KORRAS** | 200 · 1263 ms | - | 2026-09-14 15:40 |  |
| `eelis-rahvalad-linnuala`<br><sub>EELIS linnuala määramise õiguslik alus (pesastatud filter)</sub> | **KORRAS** | 200 · 1299 ms | - | 2026-09-14 15:40 |  |
| `eelis-rahvalad-seosed`<br><sub>EELIS rahvusvahelised alad koos dokumentidega (embedding)</sub> | **KORRAS** | 200 · 1257 ms | - | 2026-09-14 15:40 |  |
| `hydroseire`<br><sub>Hüdroloogiline seire, veetase 2023-01-02</sub> | **KORRAS** | 200 · 4589 ms | - | 2026-09-14 15:40 |  |
| `keskkonnaandmed-root`<br><sub>Juur-URL, OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 2333 ms | - | 2026-09-14 15:40 | body truncated at 65536 bytes, parse skipped |
| `keskkonnaseire`<br><sub>Keskkonnaseire, programm PR0127 aastal 2021</sub> | **KORRAS** | 200 · 1585 ms | - | 2026-09-14 15:40 |  |
| `kliima-element`<br><sub>Kliima elementide metaandmed</sub> | **KORRAS** | 200 · 1798 ms | - | 2026-09-14 15:40 |  |
| `kliima-jaam-vaatlus`<br><sub>Kliima vaatlusjaamade metaandmed</sub> | **KORRAS** | 200 · 1836 ms | - | 2026-09-14 15:40 |  |
| `kliima-kuu`<br><sub>Kliima kuu andmed</sub> | **KORRAS** | 200 · 1830 ms | - | 2026-09-14 15:40 |  |
| `kliima-minut`<br><sub>Kliima 10-minuti andmed</sub> | **KORRAS** | 200 · 1295 ms | - | 2026-09-14 15:40 |  |
| `kliima-paev`<br><sub>Kliima ööpäeva andmed, Ruhnu ja Kihnu õhuniiskus 2023</sub> | **KORRAS** | 200 · 1827 ms | - | 2026-09-14 15:40 |  |
| `kliima-paev-nimefilter`<br><sub>Kliima ööpäeva andmed, Võru 2006 (like-filter ja sortimine)</sub> | **KORRAS** | 200 · 1802 ms | - | 2026-09-14 15:40 |  |
| `kliima-tund`<br><sub>Kliima tunniandmed</sub> | **KORRAS** | 200 · 1809 ms | - | 2026-09-14 15:40 |  |

## Käideldavus

| Otspunkt | 24 h | 7 päeva | 30 päeva |
|---|---|---|---|
| `eelis-rahvalad` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `eelis-rahvalad-dok` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `eelis-rahvalad-linnuala` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `eelis-rahvalad-seosed` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `hydroseire` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `keskkonnaandmed-root` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `keskkonnaseire` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-element` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-jaam-vaatlus` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-kuu` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-minut` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-paev` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-paev-nimefilter` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |
| `kliima-tund` | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> | 66.7 % <sub>(n=6)</sub> |

## Katkestused

| Algus | Lõpp | Kestus | Otspunkt | Tüüp | Põhjus |
|---|---|---|---|---|---|
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `keskkonnaseire` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `hydroseire` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `eelis-rahvalad-seosed` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `eelis-rahvalad-linnuala` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `eelis-rahvalad-dok` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `eelis-rahvalad` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-tund` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-paev-nimefilter` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-paev` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-minut` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-kuu` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-jaam-vaatlus` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `kliima-element` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |
| 2026-09-14 15:16 | 2026-09-14 15:19 | 3 min | `keskkonnaandmed-root` | MAAS | http 406 Not Acceptable — {"code":"PGRST106","details":null,"hint":null,"message":"The sch |

---

Ajad on EET/EEST vööndis. Logi hoiab UTC ISO 8601 kujul kaustas `logs/`.
Seisund **TEADMATA** tähendab, et kontrollija ise ei saanud võrku — see ei lähe käideldavuse arvestusse.
