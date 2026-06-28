# Deploying Omiximo Support on k3s

Infrastructure-as-code for the Omiximo Support stack. Until now the cluster
state lived only inside the running k3s node and was unreproducible. These
manifests are the source of truth.

## Topology

| Component | Kind | Replicas | Storage | Exposed via |
|-----------|------|----------|---------|-------------|
| `db` | StatefulSet (postgres:16) | 1 | PVC `pgdata` (local-path, 8Gi) | ClusterIP `db:5432` |
| `api` | Deployment (FastAPI) | 1 (pinned) | — | NodePort 30800 |
| `frontend` | Deployment (nginx static) | 2 | — | NodePort 30173 |

Host nginx terminates TLS and proxies the public domains to the NodePorts:

- `api-support.abbamarkt.nl` → `127.0.0.1:30800`
- `support.abbamarkt.nl`     → `127.0.0.1:30173`

Keep those NodePort numbers stable or the public site breaks.

## Why the API is pinned to one replica

`app.main:app` starts background loops in its FastAPI lifespan —
`mirakl_poller`, `auto_send_executor`, `sla_monitor`. They are **in-process**.
Running two API pods would poll Mirakl twice and could send a customer reply
twice. The Deployment is therefore `replicas: 1` with `strategy: Recreate`
(old pod fully gone before the new one starts). Do not scale it until the
schedulers are extracted into a separate single-replica worker.

## Build the images

Images are built locally and imported into k3s's containerd (no registry).

```bash
cd ~/omiximo-support

# Backend
docker build -t omiximo-api:prod backend
docker save omiximo-api:prod | sudo k3s ctr images import -

# Frontend — VITE_* are baked at build time, so pass them now.
docker build -t omiximo-frontend:prod \
  --build-arg VITE_API_URL=https://api-support.abbamarkt.nl \
  --build-arg VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS=true \
  frontend
docker save omiximo-frontend:prod | sudo k3s ctr images import -
```

## Create secrets (never committed)

```bash
kubectl -n omiximo-support create secret generic omiximo-db \
  --from-literal=POSTGRES_USER=omiximo \
  --from-literal=POSTGRES_PASSWORD='<password>' \
  --from-literal=POSTGRES_DB=omiximo_support

kubectl -n omiximo-support create secret generic omiximo-env \
  --from-env-file=backend/.env
```

## Apply

```bash
kubectl apply -k k8s/
# or: kubectl apply -f k8s/00-namespace.yaml -f k8s/10-db.yaml \
#                    -f k8s/20-api.yaml -f k8s/30-frontend.yaml
```

## Register the Telegram webhook

The operator console needs Telegram to deliver **both** `callback_query` (button
taps) and `message` (slash commands + the force-reply ✏️ Edit flow). Register it
reproducibly after the API is up:

```bash
kubectl exec -n omiximo-support deploy/api -c api -- python -m scripts.set_webhook
```

If `allowed_updates` is ever set to `['callback_query']` only, Edit and every
`/command` silently break (the webhook never receives those updates).

## One-time migration from the old hostPath DB

The previous `db` Deployment stored data on an unmanaged hostPath. To move onto
the PVC-backed StatefulSet **without carrying the 18GB of historical
`message_filtered` audit spam**:

```bash
# 1. Back up the old database (full safety net).
OLD=$(kubectl get pod -n omiximo-support -l app=db -o name | head -1)
kubectl exec -n omiximo-support "$OLD" -- \
  pg_dump -U omiximo -d omiximo_support --no-owner --clean --if-exists \
  > backup-full.sql

# 2. Stop writers so the snapshot is consistent.
kubectl scale deploy/api -n omiximo-support --replicas=0

# 3. Dump schema + all data EXCEPT the audit_log spam.
kubectl exec -n omiximo-support "$OLD" -- pg_dump -U omiximo -d omiximo_support \
  --no-owner --schema-only > clean.sql
kubectl exec -n omiximo-support "$OLD" -- pg_dump -U omiximo -d omiximo_support \
  --no-owner --data-only --exclude-table-data=audit_log >> clean.sql
# audit_log: keep everything that is NOT the historical spam.
kubectl exec -n omiximo-support "$OLD" -- psql -U omiximo -d omiximo_support -c \
  "\copy (SELECT * FROM audit_log WHERE action <> 'message_filtered') TO STDOUT" \
  > audit_keep.tsv

# 4. Bring up the new StatefulSet (delete the old Deployment first), then load.
kubectl delete deploy db -n omiximo-support      # old hostPath db
kubectl apply -f k8s/10-db.yaml                  # new PVC StatefulSet
kubectl rollout status statefulset/db -n omiximo-support
NEW=db-0
kubectl exec -i -n omiximo-support "$NEW" -- psql -U omiximo -d omiximo_support < clean.sql
kubectl exec -i -n omiximo-support "$NEW" -- psql -U omiximo -d omiximo_support -c \
  "\copy audit_log FROM STDIN" < audit_keep.tsv

# 5. Restart the API against the new DB and verify.
kubectl scale deploy/api -n omiximo-support --replicas=1
kubectl exec -n omiximo-support "$NEW" -- psql -U omiximo -d omiximo_support -tAc \
  "SELECT count(*) FROM support_threads;"   # expect 124
```

Rollback: re-point at the old hostPath db (it is untouched until step 4's
`kubectl delete deploy db`), or restore `backup-full.sql` into a fresh DB.

## audit_log retention

`backend/scripts/prune_audit_log.sql` removes the historical spam and sets
per-table autovacuum on an existing DB. For a fresh migration you don't need it
(the spam is never restored). Going forward the postgres autovacuum args in
`10-db.yaml` keep the table from bloating again.
