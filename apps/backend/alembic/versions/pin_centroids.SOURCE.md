# Pin centroid seed - source, licence and derivation

`pin_centroids.csv.gz` is the committed seed the
`2022b1062d5e_v8_16__pin_centroid_table_and_seed` migration bulk-inserts into
`partner.partner_pin_centroids`. It is the data half of the parent decision
"practice position is a PIN-centroid lookup, not a geocode" (#599). The prose
half - the ADR - is #622's and is not recorded here.

## Source

| Field             | Value                                                                                                 |
| ----------------- | ----------------------------------------------------------------------------------------------------- |
| Dataset           | All India Pincode Directory till last month                                                           |
| Publisher         | Department of Posts, Ministry of Communications, Government of India                                  |
| Platform          | Open Government Data (OGD) Platform India, <https://data.gov.in/catalog/all-india-pincode-directory>  |
| Resource          | `All India Pincode Directory till last month`, resource id `5c2f62fe-5afa-4119-a499-fec9d604d5bd`     |
| Catalog id        | `709e9d78-bf11-487d-93fd-d547d24cc0ef`                                                                |
| File fetched      | <https://data.gov.in/files/ogdpv2dms/s3fs-public/dataurl03122020/pincode.csv>                         |
| Format            | CSV, 11 columns, UTF-8, LF, no BOM                                                                    |
| Size              | 23,760,720 bytes, matching the `file_size` the platform publishes for the resource                    |
| SHA-256 of source | `84af12fa29adddedfa9adddef46546000d89d2e2899b2993dc88050fafc8861e2`                                   |
| Retrieved         | 2026-09-30                                                                                            |
| Licence           | Government Open Data Licence - India (GODL), <https://data.gov.in/government-open-data-license-india> |
| Update cadence    | Monthly on the platform, so a future refresh is a new seed file plus a new migration                  |

The platform is the licensed publication and the file is served from the
`data.gov.in` apex host. The `www.data.gov.in` host returns 403 for this legacy
`/files/ogdpv2dms/dataurl*` path, so a refresh must fetch from the apex. The
file needs no API key.

### On the `dataurl03122020` path segment

The dated segment in the fetch URL is the platform's storage key, not a claim
about the data vintage: the resource is republished in place, and the same
`/files/ogdpv2dms/s3fs-public/dataurl*/pincode.csv` path is what the catalog
serves. What ties this fetch to the resource id in the table above is the byte
count - 23,760,720 matches the `file_size` the platform publishes for
resource `5c2f62fe-5afa-4119-a499-fec9d604d5bd` - together with the SHA-256
above. A refresh that no longer matches the published `file_size` is a
different payload and needs a review, not a silent re-seed.

The catalog's "till last month" title and its monthly update cadence are the
platform's own wording; neither is a licence to assume the file carries
yesterday's new offices. Treat the seed as a point in time pinned by the hashes
in this file.

Exact fetch used, for reproducibility:

```sh
curl -fsSL -o pincode.csv \
  https://data.gov.in/files/ogdpv2dms/s3fs-public/dataurl03122020/pincode.csv
sha256sum pincode.csv   # must print 84af12fa29adddedfa9adddef46546000d89d2e2899b2993dc88050fafc8861e2
stat -c %s pincode.csv  # must print 23760720
```

No third-party mirror (Kaggle, GitHub, dataful.in) was used. The only
Government of India host involved is the one above.

## Source columns

`CircleName`, `RegionName`, `DivisionName`, `OfficeName`, `Pincode`,
`OfficeType`, `Delivery`, `District`, `StateName`, `Latitude`, `Longitude`.

## Derivation

The source is one row per post office; a PIN is served by several offices. The
table's primary key is the PIN, so the seed collapses each PIN to one row.

1. **Keep only rows that resolve.** A row survives when `Pincode` is exactly six
   digits and both `Latitude` and `Longitude` parse as a number inside
   `[-90, 90]` and `[-180, 180]`. Nothing is repaired or rounded into range.
2. **Keep only rows on the Indian landmass.** A further 4,056 surviving rows sit
   outside India's bounding box, which is upstream corruption rather than a real
   office: the worst is a West Singhbhum office placed at 41.12 N, 16.87 E, which
   is Puglia in Italy. Such a row is dropped on the same judgement as an
   out-of-range one. The box used is 6.0-37.6 N and 68.0-97.5 E, which covers
   Kanyakumari (8.08 N) to northern Kashmir (37.1 N), Kutch (68.2 E) to eastern
   Arunachal (97.4 E), and the Andaman and Nicobar and Lakshadweep groups.
3. **Median per PIN, not mean.** `latitude` and `longitude` are the **median** of
   the PIN's surviving office coordinates, rounded to six decimal places to match
   the target `NUMERIC(9, 6)`. The median is used because the arithmetic mean is
   not robust here: 2,681 PIN codes have at least one surviving office more than
   100 km from the rest of the cluster, 954 of them more than 400 km, and the
   worst are about 3,200 km out. A single such row drags a mean to the wrong
   state, while the median stays on the cluster - for the worst of those PINs the
   median office sits 0-26 km from the median coordinate. That is the centroid
   of the PIN's delivery area, and it is what a doctor's map pin needs.
4. **`district` and `region`** are the most frequent value among the PIN's
   surviving offices, ties broken lexicographically. A PIN sits inside one
   district and one postal region, so the mode is that district and that region.
   `region` is India Post's `RegionName`, a subdivision of a postal circle, kept
   verbatim so the read side needs no translation table.
5. **`office_name`** is the lexicographically first `OfficeName` among the PIN's
   surviving offices. Several offices share a PIN and the key admits one, so this
   is a deterministic representative, not a claim that the PIN has a single
   office. Longest value 46 characters.
6. **Ordering.** Rows are sorted by `pin` ascending, so the seed file, the SQL
   the migration generates from it, and any diff of either are stable.

## Result

| Metric                                                | Value                                                              |
| ----------------------------------------------------- | ------------------------------------------------------------------ |
| Source rows                                           | 157,126                                                            |
| Distinct PIN codes in the source                      | 19,300                                                             |
| Rows dropped, unparseable or out of range coordinates | 9,461                                                              |
| Rows dropped, outside the Indian landmass             | 4,056                                                              |
| Rows used for the medians                             | 143,609                                                            |
| Seeded PIN rows                                       | 19,258                                                             |
| PIN codes excluded for want of a usable coordinate    | 42                                                                 |
| PINs served by more than one office                   | 16,050                                                             |
| PINs served by exactly one office                     | 3,208                                                              |
| Seed size, committed `.csv.gz`                        | 343,632 bytes (about 1.2 MB uncompressed)                          |
| SHA-256 of the committed seed                         | `e2ebf094065942c43abc4011945d7cc0a02c48e0dd3d4341019bfa5284a1b561` |

The 42 excluded PIN codes are the designed failure mode, not a gap to paper
over. The parent decision is that a PIN either resolves or it is not, with no
partial resolution, no coarse fallback and no default position, so those 42 stay
absent and the lookup honestly reports "no". Nothing in this seed invents a
not-found row, a default centroid or a nearest-neighbour stand-in.

## Known upstream quirks, left as published

- **`region` is the literal placeholder `DivReportingCircle` for 4,087 of the
  19,258 PINs.** The Department of Posts publishes that string where a circle
  has no published region subdivision, which is most single-region states. It is
  stored verbatim rather than replaced with a state name, because substituting
  one would be inventing a postal region the source never claimed. A read side
  that needs a doctor-meaningful label must decide how to present the placeholder;
  that decision belongs to #603, not to this seed.
- **`district` names are the postman's spellings**, including upstream typos such
  as `WEST SINGHBHUM` for West Singhbhum and `BENGALURU URBAN` for Bengaluru
  Urban. They are the values the operator console and the doctor's read-only
  confirmation will show, so they are stored exactly as published. Normalising
  them is a display concern.
- **The source has no `state` column in the seed.** The file carries
  `StateName`, but this table stores the six columns the migration contract
  names. A later migration can add `state` in place; it must not edit this file,
  because the migration that reads it is immutable (ADR-0003).

## Refreshing

The platform republishes the resource periodically, so this seed is a point in
time. A refresh is a new seed file plus a new migration; never edit
`pin_centroids.csv.gz` in place, because the migration that reads it is
immutable (ADR-0003). `tests/integration/test_pin_centroids.py` asserts this
file's SHA-256, so an edited seed fails the suite rather than quietly seeding
something other than what this record describes.

Re-running the seeding statement against an already-seeded database is a no-op:
the insert is `ON CONFLICT (pin) DO NOTHING`, so the first writer wins and a
partial seed is never doubled.
