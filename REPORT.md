# Keskkonnaagentuuri API-de seisundiraport

Koostatud: **2026-09-14 16:31** (EET/EEST) · jälgitavaid otspunkte: **14** · kontrollikirjeid logis: **98**

Hetkeseis — KORRAS: **14**

## Praegune seis

| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |
|---|---|---|---|---|---|
| `eelis-rahvalad`<br><sub>EELIS rahvusvahelised alad, Kurese loodusala</sub> | **KORRAS** | 200 · 830 ms | - | 2026-09-14 16:31 |  |
| `eelis-rahvalad-dok`<br><sub>EELIS rahvusvaheliste alade dokumendid, seosetabel</sub> | **KORRAS** | 200 · 832 ms | - | 2026-09-14 16:31 |  |
| `eelis-rahvalad-linnuala`<br><sub>EELIS linnuala määramise õiguslik alus (pesastatud filter)</sub> | **KORRAS** | 200 · 1298 ms | - | 2026-09-14 16:31 |  |
| `eelis-rahvalad-seosed`<br><sub>EELIS rahvusvahelised alad koos dokumentidega (embedding)</sub> | **KORRAS** | 200 · 1312 ms | - | 2026-09-14 16:31 |  |
| `hydroseire`<br><sub>Hüdroloogiline seire, veetase 2023-01-02</sub> | **KORRAS** | 200 · 3087 ms | - | 2026-09-14 16:31 |  |
| `keskkonnaandmed-root`<br><sub>Juur-URL, OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 3313 ms | - | 2026-09-14 16:31 | body truncated at 65536 bytes, parse skipped |
| `keskkonnaseire`<br><sub>Keskkonnaseire, programm PR0127 aastal 2021</sub> | **KORRAS** | 200 · 3725 ms | - | 2026-09-14 16:31 |  |
| `kliima-element`<br><sub>Kliima elementide metaandmed</sub> | **KORRAS** | 200 · 2814 ms | - | 2026-09-14 16:31 |  |
| `kliima-jaam-vaatlus`<br><sub>Kliima vaatlusjaamade metaandmed</sub> | **KORRAS** | 200 · 2821 ms | - | 2026-09-14 16:31 |  |
| `kliima-kuu`<br><sub>Kliima kuu andmed</sub> | **KORRAS** | 200 · 2815 ms | - | 2026-09-14 16:31 |  |
| `kliima-minut`<br><sub>Kliima 10-minuti andmed</sub> | **KORRAS** | 200 · 2780 ms | - | 2026-09-14 16:31 |  |
| `kliima-paev`<br><sub>Kliima ööpäeva andmed, Ruhnu ja Kihnu õhuniiskus 2023</sub> | **KORRAS** | 200 · 2835 ms | - | 2026-09-14 16:31 |  |
| `kliima-paev-nimefilter`<br><sub>Kliima ööpäeva andmed, Võru 2006 (like-filter ja sortimine)</sub> | **KORRAS** | 200 · 2858 ms | - | 2026-09-14 16:31 |  |
| `kliima-tund`<br><sub>Kliima tunniandmed</sub> | **KORRAS** | 200 · 2814 ms | - | 2026-09-14 16:31 |  |

## Käideldavus

| Otspunkt | 24 h | 7 päeva | 30 päeva |
|---|---|---|---|
| `eelis-rahvalad` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `eelis-rahvalad-dok` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `eelis-rahvalad-linnuala` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `eelis-rahvalad-seosed` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `hydroseire` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `keskkonnaandmed-root` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `keskkonnaseire` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-element` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-jaam-vaatlus` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-kuu` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-minut` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-paev` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-paev-nimefilter` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |
| `kliima-tund` | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> | 71.4 % <sub>(n=7)</sub> |

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
