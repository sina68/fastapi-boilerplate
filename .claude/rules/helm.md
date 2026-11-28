---
paths:
  - "deploy/helm/**"
---

# Helm chart rules

The chart is deployed outside the MCI cluster, so it must be **self-contained**:
no `dependencies:` on the shared `zarebin` chart or any remote/library chart,
no reliance on `bw3-ops` configmaps/secrets that will not exist there. It must
still *look like* the `bw3-ops` charts so the same people can operate both.

## Layout

```
deploy/helm/<service>/
  Chart.yaml               apiVersion v2, type application, version + appVersion
  values.yaml              defaults shared by every env (no secrets)
  values-dev.yaml          per-env overrides only
  values-stage.yaml
  values-prod.yaml
  templates/
    _helpers.tpl           fullname, labels, selectorLabels
    deployment.yaml        one Deployment per component (range over .Values.components)
    service.yaml
    ingress.yaml           from service.domains
    hpa.yaml
    pdb.yaml
    servicemonitor.yaml    only if the Prometheus operator CRD exists there
    migration-job.yaml     helm pre-install/pre-upgrade hook: alembic upgrade head
    cronjob.yaml           for scripts/*, optional
    NOTES.txt
```

## Values shape (keep keys identical to bw3-ops charts)

Per component use the same keys the `zarebin` chart uses in `bw3-ops/prod/*/values.yaml`:
`replicaCount`, `image.repository`, `image.tag`, `fullnameOverride`,
`podLabels`, `service.enabled`, `service.domains`, `service.ports[].name|port|targetPort|protocol`,
`readinessProbe` / `livenessProbe` / `startupProbe` (`port`, `path`,
`initialDelaySeconds`, `periodSeconds`, `timeoutSeconds`, `successThreshold`,
`failureThreshold`), `resources.requests|limits.cpu|memory|ephemeralStorage`,
`autoscaling.enabled|minReplicas|maxReplicas|targetCPUUtilizationPercentage|behavior`,
`servicemonitor.enabled|port|path`, `env` (list of k8s `EnvVar`, `valueFrom`
allowed). Container name stays `main`.

Components (architecture.md §21; Google Doc الف.۱, الف.۱۱), one image,
different command. API and workers scale independently:

| component | command | replicas | probes | notes |
|---|---|---|---|---|
| `api` | uvicorn (entrypoint default) | HPA | HTTP readiness / liveness | Service + ingress, ServiceMonitor |
| `scheduler` | `celery ... beat` | **exactly 1**, `strategy: Recreate`, no HPA | exec | claims sources in Postgres (`SKIP LOCKED`) |
| `worker-domestic` | `celery ... worker -Q domestic` | HPA / configurable | exec `celery inspect ping` | Iranian sites, no proxy |
| `worker-egress` | `celery ... worker -Q egress` | HPA / configurable | exec `celery inspect ping` | Telegram + filtered sources, egress proxy env |
| `worker-<group>-browser` | `celery ... worker -Q <group>_browser` | small, optional | exec | Playwright; strict CPU/memory limits; only if a source needs it |

Queues by network path are decided (AGENTS.md §4). Model workers as a map in
values (`workers.<name>.queues`, `.replicaCount`, `.resources`, `.env`) so
adding a browser worker is a values change, not a template change. The egress
proxy URL is set only on egress workers.

## Rules

- Secrets never appear in values files. Reference existing Secrets with
  `secretKeyRef` (DB password, JWT secret, proxy creds, Sentry DSN). Document
  every Secret name/key the chart expects in `values.yaml` comments and in the
  chart README/NOTES.
- Non-secret config via `env` values or a ConfigMap; names match
  `core/config.py` exactly.
- `image.tag` is set by CI/Argo CD per env; never `latest`; `imagePullPolicy`
  explicit.
- Migrations run once per release in the hook Job, not in every pod
  (`RUN_MIGRATIONS=0` for all components).
- Every container has requests and limits (CPU, memory, ephemeral storage) and
  runs as non-root (`securityContext.runAsNonRoot: true`,
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem` where possible
  with an `emptyDir` for `/home/app/logs` and `/tmp`).
- Liveness never depends on the DB or Redis (a broken dependency must not
  restart pods); readiness may.
- PDB for `api` and workers (`minAvailable: 1`); none for `scheduler`.
- CronJobs: `timeZone: "Asia/Tehran"`, `concurrencyPolicy: Forbid`,
  `activeDeadlineSeconds`, `restartPolicy: OnFailure` — same as
  `bw3-ops/prod/url-reputation-*-job`.
- Egress proxy URL is a value (e.g. `EGRESS_PROXY_URL`), set only on the
  egress worker.
- Template with `nindent`/`toYaml`; no hand-indented YAML blocks. Labels use
  `app.kubernetes.io/*`.

## Before pushing a chart change

```bash
helm lint deploy/helm/<service> -f deploy/helm/<service>/values-dev.yaml
helm template t deploy/helm/<service> -f deploy/helm/<service>/values-prod.yaml > /dev/null
```

Both must succeed for every env file you touched. Mention rendered-diff
highlights in the MR.
