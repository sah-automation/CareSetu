# Grafana - provisioned dashboards, datasource and alert rules

`deploy/grafana/provisioning/` holds the operator's Grafana configuration as
**repository files**, provisioned from configuration rather than clicked into the
console, so a dashboard change is a reviewable, revertible commit (PHASE-14A T31,
#748).

Every file here is **generated** by
`apps/backend/scripts/gen_grafana_assets.py`; the generator is the single owner of
the bytes and is unit-tested in `tests/unit/test_grafana_assets.py`. Do not
hand-edit the assets: edit the generator and regenerate.

## Layout

| Path                                                           | What it is                                                    |
| :------------------------------------------------------------- | :------------------------------------------------------------ |
| `provisioning/datasources/caresetu-postgres.yaml`              | Read-only Postgres datasource onto the `observability` schema |
| `provisioning/dashboards/caresetu-provider.yaml`               | Dashboard provider that loads the JSON below                  |
| `provisioning/dashboards/caresetu/caresetu-observability.json` | The dashboard (UID `caresetu-observability`)                  |
| `provisioning/alerting/caresetu-alerts.yaml`                   | The capped alert-rule set, including the active-series guard  |

## Two invariants the assets must keep

- **The datasource is read-only and points at `observability`.** Grafana never
  writes into the system of record, and every panel's SQL is schema-qualified, so
  the business and product numbers render from Postgres rather than a vendor's
  14-day window (`ADR-0024` D2).
- **No live vendor API behind a panel.** A panel that called the AI tracing
  vendor on refresh would exhaust the free tier's hundred-request-a-day ceiling in
  an afternoon (story 111). Grafana reads Postgres and nothing else.

## The active-series guard

Grafana Cloud's free tier allows **ten thousand** active series with **no
overage**: crossing it drops telemetry silently. The `caresetu-active-series`
alert therefore fires **below** the ceiling (at `ACTIVE_SERIES_ALERT_THRESHOLD`),
so the operator sheds a label before ingestion is lost (#717 decision 38). Panels
group HTTP status by the four-value `status_class` vocabulary, never a raw status
code, so the cardinality the free tier spends stays bounded (story 106).

The alert-rule set is capped at a small deliberate number (`MAX_ALERT_RULES`) so
the vendor's generous allowance never turns into alert fatigue; adding a rule
means arguing one out (story 104).

## Regenerating and validating

```sh
# Regenerate every asset in place:
node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py

# Fail when a committed asset is stale (CI / drift gate):
node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py --check

# The generator + committed-asset contract:
npm run test:unit:backend
```

Grafana picks the files up on boot from
`/etc/grafana/provisioning/` (mount this directory there). The files reference
these variables, which are resolved on the **Grafana host** (they are not read
by the CareSetu app, so they do not appear in the app's `.env.example`):

| Variable                         | Used by             | Meaning                                                                                               |
| :------------------------------- | :------------------ | :---------------------------------------------------------------------------------------------------- |
| `CARESETU_DB_HOST`               | datasource          | Postgres host the read-only role connects to                                                          |
| `CARESETU_DB_PORT`               | datasource          | Postgres port                                                                                         |
| `CARESETU_DB_NAME`               | datasource          | Database holding the `observability` schema                                                           |
| `CARESETU_DB_READONLY_USER`      | datasource          | The read-only Postgres role (SELECT on `observability`)                                               |
| `CARESETU_DB_READONLY_PASSWORD`  | datasource (secure) | That role's password; set in the environment, never committed                                         |
| `GRAFANA_METRICS_DATASOURCE_UID` | alert rules         | UID of the metrics datasource (Grafana Cloud Mimir/Prometheus) the alert query nodes evaluate against |

An unset `GRAFANA_METRICS_DATASOURCE_UID` resolves to empty: the alert rules
still load, but their query nodes find no datasource, so the operator sees rules
that never fire rather than a rule silently pointed at the wrong series.
