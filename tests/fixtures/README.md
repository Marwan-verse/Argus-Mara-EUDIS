# Test fixtures

`opensanctions_maritime_sample.csv` holds 38 real rows of the OpenSanctions
`maritime.csv` exported on 15 Oct 2026 (version `20261015150305-hxm`), unchanged:
the tanker BLUE, both "YANTAR" entries in GUR's list, SKAUT (formerly PONTUS I),
FENOR, APAMA, IRA, NEGA, MAERSK BOGOR, the two "Hai Zhou 168" records that share
MMSIs, one inspection-only ship and one organisation row.
Data: [OpenSanctions](https://www.opensanctions.org/datasets/maritime/), CC BY-NC 4.0.
`tests/test_watchlist.py` uses it; no test touches the network.
