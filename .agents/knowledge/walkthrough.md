# Helm Monorepo Automation System — Walkthrough (v2)

## What Was Added in This Round

Building on the base system, this iteration adds:
- **Security hardening** (strict SecurityContext with opt-in override per app)
- **Auto-mount `/tmp` as `emptyDir`** when `readOnlyRootFilesystem: true`
- **Service** resource support (ClusterIP / NodePort)
- **Ingress** resource support (nginx default, extensible for cloud ALB/etc.)
- **Env, Volumes, Affinity** declared in `apps_definition.yaml`
- A 3rd test service (`payment-service`) with override security context and custom Ingress class

---

## Final Library Chart Structure

```text
helm-templates/common-lib/templates/
├── _helpers.tpl       # Labels, naming, selectors
├── _deployment.yaml   # Deployment (securityContext injection, env, volumes, affinity)
├── _service.yaml      # Service (ClusterIP / NodePort)
├── _ingress.yaml      # Ingress (nginx default, cloud-provider extensible)
└── _main.tpl          # Router → renders Deployment + conditionally Service + Ingress
```

---

## Security Context Design

### Default (applied to all apps unless overridden)

```yaml
securityContext:
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop: [ALL]
```

### Override Rules

| Field | Source | Behavior |
|---|---|---|
| `security_context.*` | `apps_definition.yaml` per-app `config:` | Full merge — any specified key overrides the default |
| `capabilities` | `apps_definition.yaml` | Full replacement (not merge) when specified |
| `auto_mount_tmp` | `apps_definition.yaml` (default: `true`) | Auto-adds `emptyDir` volume + mount at `/tmp` when `readOnlyRootFilesystem: true` |

---

## apps_definition.yaml — 3-App Matrix

| App | SecurityContext | `/tmp` auto-mount | Service | Ingress Class | Notes |
|---|---|---|---|---|---|
| `api-gateway` | Default (hardened) | ✅ auto | ClusterIP :80 | nginx | + env, configMap volume, podAntiAffinity |
| `user-service` | Default (hardened) | ✅ auto | ClusterIP :8081 | — | Minimal config, no override |
| `payment-service` | **Override** (runAsUser: 0) | ❌ (readOnlyRootFilesystem: false) | ClusterIP :80 | `my-cloud-alb` | Legacy app, ALB annotations |

---

## Verified helm template Output (Highlights)

### api-gateway
```yaml
# Deployment: security context + /tmp + env + configMap + affinity
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
volumeMounts:
  - mountPath: /etc/config
    name: config-volume
  - mountPath: /tmp
    name: api-gateway-tmp   # auto-injected emptyDir

# Service: ClusterIP port 80 → 8080
# Ingress: nginx class, host api.my-platform.com, path /
```

### user-service
```yaml
# Security: same hardened defaults (no override in apps_definition.yaml)
# /tmp auto-mounted since readOnlyRootFilesystem: true
# Service only, no Ingress
```

### payment-service
```yaml
# Override: runAsUser: 0, readOnlyRootFilesystem: false
# No /tmp auto-mount (R/O FS disabled)
# Ingress: class my-cloud-alb, ALB annotation, path /api/v1/pay
```

---

## How Ingress Classes Work

The `_ingress.yaml` template auto-injects nginx-specific annotations when `className` is `nginx` (or empty):
```yaml
nginx.ingress.kubernetes.io/ssl-redirect: "false"
nginx.ingress.kubernetes.io/proxy-body-size: "8m"
```
For any other `className` (e.g. `my-cloud-alb`), no default annotations are injected — only the annotations declared in `apps_definition.yaml` are used.

---

## How to Add a New App

```yaml
# In apps_definition.yaml:
- name: "my-new-service"
  type: "deployment"
  config:
    image_repo: "registry.vn/my-service"
    port: 9090
    replicas: 2
    # Optional: security override
    security_context:
      runAsUser: 500
    # Optional: Service
    service:
      enabled: true
      port: 80
    # Optional: Ingress
    ingress:
      enabled: true
      className: nginx
      hosts:
        - host: "my-service.example.com"
          paths:
            - path: /
              pathType: Prefix
```

Then run:
```bash
python3 scripts/generator.py
helm dependency update charts/my-new-service
helm template my-new-service charts/my-new-service \
  --values charts/my-new-service/values.yaml \
  --values charts/my-new-service/images.yaml
```

> [!TIP]
> ArgoCD `ApplicationSet` will auto-discover the new `charts/my-new-service/` directory on the next Git sync — no manual ArgoCD configuration needed.
