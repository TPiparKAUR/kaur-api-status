# Keskkonnaagentuuri API-de seisundiraport

Koostatud: **2026-09-14 15:22** (EET/EEST) · jälgitavaid otspunkte: **14** · kontrollikirjeid logis: **56**

Hetkeseis — KORRAS: **14**

## Praegune seis

| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |
|---|---|---|---|---|---|
| `eelis-rahvalad`<br><sub>EELIS rahvusvahelised alad, Kurese loodusala</sub> | **KORRAS** | 200 · 1653 ms | - | 2026-09-14 15:21 |  |
| `eelis-rahvalad-dok`<br><sub>EELIS rahvusvaheliste alade dokumendid, seosetabel</sub> | **KORRAS** | 200 · 1646 ms | - | 2026-09-14 15:21 |  |
| `eelis-rahvalad-linnuala`<br><sub>EELIS linnuala määramise õiguslik alus (pesastatud filter)</sub> | **KORRAS** | 200 · 1636 ms | - | 2026-09-14 15:21 |  |
| `eelis-rahvalad-seosed`<br><sub>EELIS rahvusvahelised alad koos dokumentidega (embedding)</sub> | **KORRAS** | 200 · 1701 ms | - | 2026-09-14 15:21 |  |
| `hydroseire`<br><sub>Hüdroloogiline seire, veetase 2023-01-02</sub> | **KORRAS** | 200 · 13343 ms | - | 2026-09-14 15:21 |  |
| `keskkonnaandmed-root`<br><sub>Juur-URL, OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 2134 ms | - | 2026-09-14 15:21 | body truncated at 65536 bytes, parse skipped |
| `keskkonnaseire`<br><sub>Keskkonnaseire, programm PR0127 aastal 2021</sub> | **KORRAS** | 200 · 1390 ms | - | 2026-09-14 15:21 |  |
| `kliima-element`<br><sub>Kliima elementide metaandmed</sub> | **KORRAS** | 200 · 1795 ms | - | 2026-09-14 15:21 |  |
| `kliima-jaam-vaatlus`<br><sub>Kliima vaatlusjaamade metaandmed</sub> | **KORRAS** | 200 · 2267 ms | - | 2026-09-14 15:21 |  |
| `kliima-kuu`<br><sub>Kliima kuu andmed</sub> | **KORRAS** | 200 · 2285 ms | - | 2026-09-14 15:21 |  |
| `kliima-minut`<br><sub>Kliima 10-minuti andmed</sub> | **KORRAS** | 200 · 2262 ms | - | 2026-09-14 15:21 |  |
| `kliima-paev`<br><sub>Kliima ööpäeva andmed, Ruhnu ja Kihnu õhuniiskus 2023</sub> | **KORRAS** | 200 · 2251 ms | - | 2026-09-14 15:21 |  |
| `kliima-paev-nimefilter`<br><sub>Kliima ööpäeva andmed, Võru 2006 (like-filter ja sortimine)</sub> | **KORRAS** | 200 · 2300 ms | - | 2026-09-14 15:21 |  |
| `kliima-tund`<br><sub>Kliima tunniandmed</sub> | **KORRAS** | 200 · 2244 ms | - | 2026-09-14 15:21 |  |

## Käideldavus

| Otspunkt | 24 h | 7 päeva | 30 päeva |
|---|---|---|---|
| `eelis-rahvalad` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `eelis-rahvalad-dok` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `eelis-rahvalad-linnuala` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `eelis-rahvalad-seosed` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `hydroseire` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `keskkonnaandmed-root` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `keskkonnaseire` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-element` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-jaam-vaatlus` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-kuu` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-minut` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-paev` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-paev-nimefilter` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |
| `kliima-tund` | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> | 50.0 % <sub>(n=4)</sub> |

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
