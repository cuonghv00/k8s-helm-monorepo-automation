# Technical Specification: Helm Monorepo Automation System

## 1. Context & Objective
Build an automation system for a Kubernetes Monorepo containing ~15 microservices. The system must use a **Library Chart** pattern to ensure DRY (Don't Repeat Yourself) while allowing independent deployments and upgrades via **ArgoCD**.

## 2. Directory Structure
```text
.
├── helm-templates/
│   └── common-lib/          # Core logic (Library Chart)
├── charts/                  # Generated Application Charts (Managed by Script)
│   ├── app-a/
│   └── app-b/
├── scripts/
│   └── generator.py         # The Python "Engine"
└── apps_definition.yaml     # Single Source of Truth for all apps
```

## 3. Component Requirements

### A. Library Chart (`common-lib`)
- **Type:** `library`.
- **Templates:** Must include reusable blocks (`define`) for:
    - `Deployment`, `StatefulSet`, `Job`, `CronJob`.
    - `Service` (ClusterIP/LoadBalancer).
    - `Ingress` (supporting annotations for NGINX).
- **Logic:** Use a `main.yaml` as a router to include the correct resource based on `.Values.type`.

### B. Input Schema (`apps_definition.yaml`)
```yaml
project: "my-platform"
common_version: "1.0.0"
apps:
  - name: "api-gateway"
    type: "deployment"
    config:
      image_repo: "registry.vn/gateway"
      port: 8080
      replicas: 3
  - name: "order-db"
    type: "statefulset"
    config:
      image_repo: "postgres"
      storage: "20Gi"
```

### C. Python Generator (`generator.py`)
- **Task:** Read `apps_definition.yaml` and for each app:
    1. Create/Update directory in `charts/<app-name>`.
    2. Generate `Chart.yaml` with a dependency on `common-lib` (using `file://` path).
    3. Generate `values.yaml` mapping input config to `common-lib` values.
    4. Create an empty `images.yaml` (used for CI tag updates).
- **Requirement:** Must be idempotent (running multiple times shouldn't break existing charts).

### D. CI/CD Integration (GitLab API)
- **Task:** Update `images.yaml` via GitLab Commits API.
- **Workflow:**
    1. Build image -> Get `$CI_PIPELINE_ID`.
    2. Call API to update `charts/<app-name>/images.yaml` with the new tag.
    3. **Constraint:** Use GitLab `resource_group` to prevent 409 Conflicts.
    4. **Commit Message:** Must include `[skip ci]`.

## 4. Implementation Tasks for AI Agent
1. **Task 1:** Write the `common-lib` templates (focus on `_helpers.tpl` and `deployment.yaml`).
2. **Task 2:** Write the `generator.py` using `PyYAML` and `Jinja2` (optional).
3. **Task 3:** Create a sample `.gitlab-ci.yml` demonstrating the `resource_group` and API call logic.
4. **Task 4:** Provide an `ApplicationSet` manifest for ArgoCD to auto-discover folders in `charts/`.

## 5. Definition of Done
- A new app added to `apps_definition.yaml` results in a deployable Helm chart after running the script.
- Independent `helm upgrade` commands can be run for each sub-directory in `charts/`.
- CI can update image tags without Git merge conflicts.