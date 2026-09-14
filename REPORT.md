# Keskkonnaagentuuri API-de seisundiraport

Koostatud: **2026-09-14 15:19** (EET/EEST) · jälgitavaid otspunkte: **14** · kontrollikirjeid logis: **42**

Hetkeseis — KORRAS: **14**

## Praegune seis

| Otspunkt | Seisund | Vastus | Andmete vanus | Viimane kontroll | Märkus |
|---|---|---|---|---|---|
| `eelis-rahvalad`<br><sub>EELIS rahvusvahelised alad, Kurese loodusala</sub> | **KORRAS** | 200 · 1269 ms | - | 2026-09-14 15:19 |  |
| `eelis-rahvalad-dok`<br><sub>EELIS rahvusvaheliste alade dokumendid, seosetabel</sub> | **KORRAS** | 200 · 1255 ms | - | 2026-09-14 15:19 |  |
| `eelis-rahvalad-linnuala`<br><sub>EELIS linnuala määramise õiguslik alus (pesastatud filter)</sub> | **KORRAS** | 200 · 1266 ms | - | 2026-09-14 15:19 |  |
| `eelis-rahvalad-seosed`<br><sub>EELIS rahvusvahelised alad koos dokumentidega (embedding)</sub> | **KORRAS** | 200 · 1276 ms | - | 2026-09-14 15:19 |  |
| `hydroseire`<br><sub>Hüdroloogiline seire, veetase 2023-01-02</sub> | **KORRAS** | 200 · 2173 ms | - | 2026-09-14 15:19 |  |
| `keskkonnaandmed-root`<br><sub>Juur-URL, OpenAPI teenusekirjeldus</sub> | **KORRAS** | 200 · 3728 ms | - | 2026-09-14 15:19 | body truncated at 4194304 bytes, parse skipped |
| `keskkonnaseire`<br><sub>Keskkonnaseire, programm PR0127 aastal 2021</sub> | **KORRAS** | 200 · 3364 ms | - | 2026-09-14 15:19 |  |
| `kliima-element`<br><sub>Kliima elementide metaandmed</sub> | **KORRAS** | 200 · 1893 ms | - | 2026-09-14 15:19 |  |
| `kliima-jaam-vaatlus`<br><sub>Kliima vaatlusjaamade metaandmed</sub> | **KORRAS** | 200 · 3035 ms | - | 2026-09-14 15:19 |  |
| `kliima-kuu`<br><sub>Kliima kuu andmed</sub> | **KORRAS** | 200 · 1900 ms | - | 2026-09-14 15:19 |  |
| `kliima-minut`<br><sub>Kliima 10-minuti andmed</sub> | **KORRAS** | 200 · 1654 ms | - | 2026-09-14 15:19 |  |
| `kliima-paev`<br><sub>Kliima ööpäeva andmed, Ruhnu ja Kihnu õhuniiskus 2023</sub> | **KORRAS** | 200 · 1912 ms | - | 2026-09-14 15:19 |  |
| `kliima-paev-nimefilter`<br><sub>Kliima ööpäeva andmed, Võru 2006 (like-filter ja sortimine)</sub> | **KORRAS** | 200 · 1899 ms | - | 2026-09-14 15:19 |  |
| `kliima-tund`<br><sub>Kliima tunniandmed</sub> | **KORRAS** | 200 · 1855 ms | - | 2026-09-14 15:19 |  |

## Käideldavus

| Otspunkt | 24 h | 7 päeva | 30 päeva |
|---|---|---|---|
| `eelis-rahvalad` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `eelis-rahvalad-dok` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `eelis-rahvalad-linnuala` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `eelis-rahvalad-seosed` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `hydroseire` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `keskkonnaandmed-root` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `keskkonnaseire` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-element` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-jaam-vaatlus` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-kuu` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-minut` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-paev` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-paev-nimefilter` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |
| `kliima-tund` | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> | 33.3 % <sub>(n=3)</sub> |

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

## Hoiatused

- `eelis-rahvalad-dok`: URL on **kontrollimata** (`verified = false`) — allikas: manual
- `kliima-kuu`: URL on **kontrollimata** (`verified = false`) — allikas: manual
- `kliima-minut`: URL on **kontrollimata** (`verified = false`) — allikas: manual
- `kliima-tund`: URL on **kontrollimata** (`verified = false`) — allikas: manual

---

Ajad on EET/EEST vööndis. Logi hoiab UTC ISO 8601 kujul kaustas `logs/`.
Seisund **TEADMATA** tähendab, et kontrollija ise ei saanud võrku — see ei lähe käideldavuse arvestusse.
