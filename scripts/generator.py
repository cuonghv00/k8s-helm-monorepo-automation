#!/usr/bin/env python3
"""
generator.py
============
The Python "Engine" for the Helm Monorepo Automation System.

Reads apps.{env}.yaml (Single Source of Truth) and for each app:
  1. Creates/updates the directory at projects/{env}/{project}/charts/<app-name>/
  2. Generates Chart.yaml with a file:// dependency on common-lib
  3. Generates values.yaml mapping app config to common-lib value keys

Design principle: IDEMPOTENT — safe to run multiple times without side effects.
"""

import argparse
import sys
import re
from pathlib import Path
from typing import Optional, Union, Any

import yaml
from pydantic import BaseModel, Field, RootModel, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------
DEFAULT_REGISTRY = "registry.vn/platform"
DEFAULT_PULL_SECRET = "regcred"
COMMON_LIB_REL_PATH = "../../../../../helm-templates/common-lib"

# ---------------------------------------------------------------------------
# Pydantic Models for Configuration Validation
# ---------------------------------------------------------------------------

class IngressPath(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = "/"
    pathType: str = "ImplementationSpecific"
    servicePort: Optional[Union[int, str]] = None 

class IngressHost(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host: str
    paths: list[IngressPath] = Field(default_factory=lambda: [IngressPath()])

class IngressConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    host: Optional[str] = None 
    path: Optional[str] = None # Shortcut
    hosts: Optional[list[IngressHost]] = None
    servicePort: Optional[Union[int, str]] = None
    annotations: dict[str, str] = Field(default_factory=dict)
    className: str = "nginx"

class ProbeConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: Optional[str] = None
    port: Optional[Union[int, str]] = None
    initialDelaySeconds: int = 10
    periodSeconds: int = 5
    timeoutSeconds: int = 2
    failureThreshold: int = 3

class HealthConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    path: Optional[str] = None
    port: Optional[Union[int, str]] = None
    initialDelaySeconds: int = 10
    periodSeconds: int = 5
    timeoutSeconds: int = 2
    failureThreshold: int = 3
    liveness: Optional[Union[str, ProbeConfig]] = None
    readiness: Optional[Union[str, ProbeConfig]] = None
    startup: Optional[Union[str, ProbeConfig]] = None

class PVCConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    size: str = "10Gi"
    storageClass: Optional[str] = None
    accessModes: list[str] = Field(default_factory=lambda: ["ReadWriteOnce"])
    mountPath: Optional[str] = None

class ServicePort(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = "http"
    port: int
    targetPort: Optional[int] = None
    protocol: str = "TCP"
    nodePort: Optional[int] = None

class ServiceAccountConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    create: bool = True
    automountToken: bool = False # Hardened default (RBAC Security)
    name: Optional[str] = None

class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    type: str = "ClusterIP"
    port: Optional[int] = None # Shortcut
    targetPort: Optional[int] = None # Shortcut
    ports: list[ServicePort] = Field(default_factory=list)
    annotations: dict[str, str] = Field(default_factory=dict)

class AppConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    
    name: str
    type: str = "deployment"
    
    port: Optional[int] = None
    ports: list[ServicePort] = Field(default_factory=list)
    
    replicas: int = 1
    image: Optional[str] = None
    image_repo: Optional[str] = None
    image_tag: Optional[str] = None
    pullPolicy: str = "IfNotPresent"
    imagePullSecrets: Optional[list[dict]] = None
    
    resources: dict = Field(default_factory=dict)
    securityContext: dict = Field(default_factory=dict)
    auto_mount_tmp: bool = True
    mount_env_file: bool = False
    
    env: list[dict] = Field(default_factory=list)
    env_vars: list[str] = Field(default_factory=list)
    envFrom: list[dict] = Field(default_factory=list)
    
    service: Optional[Union[bool, ServiceConfig]] = None
    ingress: IngressConfig = Field(default_factory=IngressConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    pvc: PVCConfig = Field(default_factory=PVCConfig)
    serviceAccount: ServiceAccountConfig = Field(default_factory=ServiceAccountConfig)
    
    strategy: str = "RollingUpdate"
    affinity: dict = Field(default_factory=dict)
    tolerations: list = Field(default_factory=list)
    serviceAccountName: Optional[str] = None # For compatibility, prefer serviceAccount.name
    genConfigMaps: bool = False
    podAnnotations: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_ports_uniqueness(self) -> 'AppConfig':
        names = [p.name for p in self.ports]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate port names detected in app '{self.name}': {names}")
        
        ports = [p.port for p in self.ports]
        if len(ports) != len(set(ports)):
            raise ValueError(f"Duplicate port numbers detected in app '{self.name}': {ports}")
        
        return self

class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project: str
    common_version: str = "1.0.0"
    namespace: Optional[str] = None
    image_repo: Optional[str] = None
    image_tag: str = "latest"
    imagePullSecrets: Optional[list[dict]] = None
    apps: list[AppConfig] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# File Utilities
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
COMMON_LIB_PATH = REPO_ROOT / "helm-templates" / "common-lib"

def parse_env_file(env_path: Path) -> tuple[dict, list]:
    config_data = {}
    secret_keys = []
    if not env_path.exists(): return config_data, secret_keys
    pattern = re.compile(r"^\s*([\w.-]+)\s*=\s*(.*)\s*$")
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            match = pattern.match(line)
            if match:
                key, value = match.groups()
                value = value.strip("'\"")
                if value.startswith("${") and value.endswith("}"): secret_keys.append(key)
                else: config_data[key] = value
    return config_data, secret_keys

def write_yaml(path: Path, data: dict, dry_run: bool = False) -> None:
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if dry_run:
        print(f"  [DRY-RUN] Would write: {path}")
        print("  " + content.replace("\n", "\n  "))
    else:
        path.write_text(content)
        print(f"  [WRITE]   {path}")

def ensure_dir(path: Path, dry_run: bool = False) -> None:
    if not path.exists():
        if not dry_run: path.mkdir(parents=True, exist_ok=True)
        print(f"  [MKDIR]   {path}")

# ---------------------------------------------------------------------------
# Logic Builders
# ---------------------------------------------------------------------------

def build_values_yaml(app: AppConfig, project: ProjectDefinition, project_vars: tuple[dict, list], image_tag: str = None) -> dict:
    config_pool, secret_pool = project_vars
    project_name = project.project
    
    # 1. Resolve Ports
    all_ports = app.ports.copy()
    if app.port and not any(p.port == app.port for p in all_ports):
        # Fallback for old single 'port' config
        all_ports.insert(0, ServicePort(name="http", port=app.port))
    
    if not all_ports:
        all_ports.append(ServicePort(name="http", port=80))

    # Port resolution for different contexts
    primary_svc_port = all_ports[0].port
    primary_container_port = all_ports[0].targetPort or all_ports[0].port

    # 2. Image logic
    image_repo = app.image_repo or project.image_repo or DEFAULT_REGISTRY
    tag = image_tag or app.image_tag or project.image_tag
    image_name = app.image if app.image else f"{image_repo}/{app.name}"

    # 3. Security & Volumes
    default_sec_ctx = {
        "readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
        "runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
        "capabilities": {"drop": ["ALL"]}
    }
    sec_ctx = {**default_sec_ctx, **app.securityContext}
    volumes, volume_mounts = [], []
    if sec_ctx.get("readOnlyRootFilesystem") and app.auto_mount_tmp:
        volumes.append({"name": "tmp", "emptyDir": {}})
        volume_mounts.append({"name": "tmp", "mountPath": "/tmp"})
    if app.mount_env_file:
        volumes.append({"name": "env-file", "configMap": {"name": f"{project_name}-config"}})
        volume_mounts.append({"name": "env-file", "mountPath": "/app/.env", "subPath": ".env"})
    if app.pvc.enabled and app.pvc.mountPath:
        volumes.append({"name": "data-volume", "persistentVolumeClaim": {"claimName": '{{ include "common-lib.fullname" . }}'}})
        volume_mounts.append({"name": "data-volume", "mountPath": app.pvc.mountPath})

    # 4. Probes
    liveness, readiness, startup = None, None, None
    if app.health.enabled:
        def make_probe(cfg_union: Union[str, ProbeConfig, None]):
            if not cfg_union: p = ProbeConfig(path=app.health.path, port=app.health.port or primary_container_port)
            elif isinstance(cfg_union, str): p = ProbeConfig(path=cfg_union, port=app.health.port or primary_container_port)
            else:
                p = cfg_union
                if not p.port: p.port = app.health.port or primary_container_port
                if not p.path: p.path = app.health.path
            res = {"initialDelaySeconds": p.initialDelaySeconds, "periodSeconds": p.periodSeconds, "timeoutSeconds": p.timeoutSeconds, "failureThreshold": p.failureThreshold}
            if p.path: res["httpGet"] = {"path": p.path, "port": p.port}
            else: res["tcpSocket"] = {"port": p.port}
            return res
        liveness, readiness, startup = make_probe(app.health.liveness), make_probe(app.health.readiness), make_probe(app.health.startup)

    # 5. Service Configuration
    svc_values = {"enabled": False}
    svc_enabled = (app.service is not False) and (app.service is not None or app.ingress.enabled)
    if svc_enabled:
        s = app.service if isinstance(app.service, ServiceConfig) else ServiceConfig()
        svc_ports = []
        source_ports = s.ports.copy()
        if s.port and not any(p.port == s.port for p in source_ports):
            source_ports.insert(0, ServicePort(name="http", port=s.port, targetPort=s.targetPort))
        for p in (source_ports if source_ports else all_ports):
            svc_ports.append({"name": p.name, "port": p.port, "targetPort": p.targetPort or p.port, "protocol": p.protocol, "nodePort": p.nodePort})
        svc_values = {"enabled": True, "type": s.type, "ports": svc_ports, "annotations": s.annotations}

    # 6. Ingress Configuration
    ing_values = {"enabled": False}
    if app.ingress.enabled:
        ing_values = app.ingress.model_dump(exclude_none=True)
        if app.ingress.host and not app.ingress.hosts:
            ing_values["hosts"] = [{"host": app.ingress.host, "paths": [{"path": app.ingress.path or "/", "pathType": "ImplementationSpecific"}]}]
        default_svc_port = app.ingress.servicePort or svc_ports[0]["port"] if svc_enabled else primary_svc_port
        for h in ing_values.get("hosts", []):
            for p in h.get("paths", []):
                if not p.get("servicePort"): p["servicePort"] = default_svc_port

    # 7. Env & Assembly
    env_list = app.env.copy()
    for key in app.env_vars:
        if key in secret_pool:
            env_list.append({"name": key, "valueFrom": {"secretKeyRef": {"name": f"{project_name}-secret", "key": key}}})
    env_from = [{"configMapRef": {"name": f"{project_name}-config"}}] + app.envFrom

    # 8. Assembly
    deploy_ports = []
    for p in all_ports:
        dp = {"name": p.name, "containerPort": p.targetPort or p.port, "protocol": p.protocol}
        deploy_ports.append(dp)

    return {
        "type": app.type,
        "image": {"repository": image_name, "tag": tag, "pullPolicy": app.pullPolicy},
        "deployment": {
            "replicas": app.replicas,
            "containerPort": primary_container_port,
            "ports": deploy_ports,
            "resources": app.resources, "strategy": {"type": app.strategy},
            "securityContext": sec_ctx, "envFrom": env_from, "env": env_list,
            "volumes": volumes, "volumeMounts": volume_mounts, "affinity": app.affinity,
            "livenessProbe": liveness, "readinessProbe": readiness, "startupProbe": startup,
            "imagePullSecrets": app.imagePullSecrets or project.imagePullSecrets or [{"name": DEFAULT_PULL_SECRET}],
            "podAnnotations": app.podAnnotations
        },
        "serviceAccount": {
            "create": app.serviceAccount.create,
            "name": app.serviceAccount.name or app.serviceAccountName,
            "automountServiceAccountToken": app.serviceAccount.automountToken
        },
        "service": svc_values, "ingress": ing_values,
        "pvc": app.pvc.model_dump(exclude_none=True), "localConfig": {"enabled": app.genConfigMaps}
    }

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

ALL_YAML_CONTENT = """{{/* Auto-generated by generator.py */}}\n{{ include "common-lib.main" . }}\n"""

def main():
    parser = argparse.ArgumentParser(description="GitOps Engine Generator")
    parser.add_argument("--project", required=True)
    parser.add_argument("--env", default="dev")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--image-tag")
    args = parser.parse_args()

    # Paths
    project_dir = REPO_ROOT / "projects" / args.env / args.project
    definition_path = project_dir / f"apps.{args.env}.yaml"
    env_path = project_dir / f"apps.{args.env}.env"
    output_dir = project_dir / "charts"

    if not definition_path.exists():
        print(f"ERROR: Definition not found at {definition_path}"); sys.exit(1)

    with definition_path.open() as f: data = yaml.safe_load(f)
    try: project_def = ProjectDefinition(**data)
    except Exception as e:
        print(f"ERROR: Validation failed for {definition_path}:\n{e}"); sys.exit(1)

    project_vars = parse_env_file(env_path)
    CHARTS_DIR = output_dir.resolve()
    print(f"=== GitOps Engine Generator (RBAC Hardened) ===\nProject: {project_def.project} | Env: {args.env}")
    
    # Generate Shared Chart
    if project_vars[0] or project_vars[1]:
        shared_dir = CHARTS_DIR / "project-shared"
        ensure_dir(shared_dir, args.dry_run)
        ensure_dir(shared_dir / "templates", args.dry_run)
        if not args.dry_run:
            desc = {"apiVersion": "v2", "name": f"{project_def.project}-shared", "description": "Shared resources", "type": "application", "version": "0.1.0", "dependencies": [{"name": "common-lib", "version": project_def.common_version, "repository": f"file://{COMMON_LIB_REL_PATH}", "alias": "common-lib"}]}
            write_yaml(shared_dir / "Chart.yaml", desc, False)
            cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": f"{project_def.project}-config"}, "data": project_vars[0]}
            write_yaml(shared_dir / "templates" / "configmap.yaml", cm, False)

    # Generate App Charts
    for app in project_def.apps:
        chart_dir = CHARTS_DIR / app.name
        ensure_dir(chart_dir, args.dry_run)
        ensure_dir(chart_dir / "templates", args.dry_run)
        if not args.dry_run:
            (chart_dir / "templates" / "all.yaml").write_text(ALL_YAML_CONTENT)
            desc = {"apiVersion": "v2", "name": app.name, "description": f"Chart for {app.name}", "type": "application", "version": "0.1.0", "dependencies": [{"name": "common-lib", "version": project_def.common_version, "repository": f"file://{COMMON_LIB_REL_PATH}", "alias": "common-lib"}]}
            write_yaml(chart_dir / "Chart.yaml", desc, False)
            write_yaml(chart_dir / "values.yaml", build_values_yaml(app, project_def, project_vars, args.image_tag), False)

    print(f"\n✅ Manifests generated in {output_dir}")

if __name__ == "__main__":
    main()
