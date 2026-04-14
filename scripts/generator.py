#!/usr/bin/env python3
"""
generator.py
============
The Python "Engine" for the Helm Monorepo Automation System.

Reads apps_definition.yaml (Single Source of Truth) and for each app:
  1. Creates/updates the directory at charts/<app-name>/
  2. Generates Chart.yaml with a file:// dependency on common-lib
  3. Generates values.yaml mapping app config to common-lib value keys
  4. Creates an empty images.yaml if it does not already exist (CI writes to it)

Design principle: IDEMPOTENT — safe to run multiple times without side effects.

Usage:
  # Single-project mode (root-level, default):
  python3 scripts/generator.py [--dry-run]

  # Multi-project mode (one sub-directory per project under projects/):
  python3 scripts/generator.py --project <name> [--dry-run]

  # Advanced: fully custom paths (overrides --project):
  python3 scripts/generator.py --definition PATH --output-dir DIR [--dry-run]

Requirements:
  pip install -r scripts/requirements.txt
"""

import argparse
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths (relative to repo root, resolved at runtime)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
APPS_DEFINITION_DEFAULT = REPO_ROOT / "apps_definition.yaml"
COMMON_LIB_PATH = REPO_ROOT / "helm-templates" / "common-lib"

# Global state updated in main()
CHARTS_DIR = REPO_ROOT / "charts"
COMMON_LIB_REL = "../../helm-templates/common-lib"


# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------

def build_chart_yaml(app_name: str, common_version: str) -> dict:
    """
    Builds the Chart.yaml content for a child application chart.
    The chart depends on common-lib via a local file:// path so that
    `helm dependency update` resolves it without a Chart Museum.
    """
    return {
        "apiVersion": "v2",
        "name": app_name,
        "description": f"Application chart for {app_name} — managed by generator.py",
        "type": "application",
        "version": "0.1.0",
        "dependencies": [
            {
                "name": "common-lib",
                "version": common_version,
                "repository": f"file://{COMMON_LIB_REL}",
                "alias": "common-lib",
            }
        ],
    }


def build_values_yaml(app: dict) -> dict:
    """
    Maps the flat app config from apps_definition.yaml to the nested
    values structure expected by common-lib templates.
    """
    cfg = app.get("config", {})

    # Base Security Context (Maximum Hardening)
    sec_ctx = {
        "readOnlyRootFilesystem": True,
        "allowPrivilegeEscalation": False,
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "capabilities": {"drop": ["ALL"]}
    }
    
    # Merge override logic
    app_sec_ctx = cfg.get("security_context", {})
    if app_sec_ctx:
        sec_ctx.update(app_sec_ctx)
        if "capabilities" in app_sec_ctx:
            sec_ctx["capabilities"] = app_sec_ctx["capabilities"]

    # Volumes and Temp Mount
    volumes = cfg.get("volumes", [])
    volume_mounts = cfg.get("volume_mounts", [])
    
    # Auto-mount /tmp by default to prevent application crash on R/O FS
    if sec_ctx.get("readOnlyRootFilesystem") and cfg.get("auto_mount_tmp", True):
        tmp_vol_name = f"{app['name']}-tmp"
        if not any(v.get("name") == tmp_vol_name for v in volumes):
            volumes.append({"name": tmp_vol_name, "emptyDir": {}})
            volume_mounts.append({"name": tmp_vol_name, "mountPath": "/tmp"})

    values: dict = {
        "type": app["type"],
        "image": {
            "repository": cfg.get("image_repo", "registry.example.com/app"),
            "tag": cfg.get("tag", "latest"),
            "pullPolicy": cfg.get("pull_policy", "IfNotPresent"),
        },
        "deployment": {
            "replicas": cfg.get("replicas", 1),
            "containerPort": cfg.get("port", 80),
            "resources": cfg.get("resources", {}),
            "strategy": {"type": "RollingUpdate"},
            "securityContext": sec_ctx,
            "env": cfg.get("env", []),
            "volumes": volumes,
            "volumeMounts": volume_mounts,
            "affinity": cfg.get("affinity", {})
        },
        "serviceAccount": {
            "create": False,
            "name": "",
        },
        "service": cfg.get("service", {}),
        "ingress": cfg.get("ingress", {})
    }

    return values


def build_images_yaml() -> dict:
    """
    Stub file written once. CI pipeline updates image.tag here via
    the GitLab Commits API without touching values.yaml (avoids merge conflicts).
    """
    return {
        "image": {
            "tag": "latest",
        }
    }


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def write_yaml(path: Path, data: dict, dry_run: bool = False) -> None:
    """Writes a dict as YAML to the given path. Skips write in dry-run mode."""
    content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if dry_run:
        print(f"  [DRY-RUN] Would write: {path}")
        print("  " + content.replace("\n", "\n  "))
    else:
        path.write_text(content)
        print(f"  [WRITE]   {path}")


def ensure_dir(path: Path, dry_run: bool = False) -> None:
    """Creates a directory (and parents) if it doesn't exist."""
    if not path.exists():
        if dry_run:
            print(f"  [DRY-RUN] Would create directory: {path}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"  [MKDIR]   {path}")
    else:
        print(f"  [EXISTS]  {path}")


# ---------------------------------------------------------------------------
# Core generator logic
# ---------------------------------------------------------------------------

ALL_YAML_CONTENT = """\
{{/*
  all.yaml — Auto-generated by scripts/generator.py. Do NOT edit manually.
  Calls the common-lib.main router which renders the correct Kubernetes
  resource based on .Values.type defined in values.yaml.
*/}}
{{ include "common-lib.main" . }}
"""


def generate_chart(app: dict, common_version: str, dry_run: bool = False) -> None:
    """Generates or updates the Helm chart directory for a single app."""
    app_name: str = app["name"]
    chart_dir = CHARTS_DIR / app_name

    print(f"\n▶  Processing app: {app_name} (type={app['type']})")

    # 1. Create chart directory
    ensure_dir(chart_dir, dry_run)

    # 2. Create templates/ with the single router-call file (all.yaml)
    ensure_dir(chart_dir / "templates", dry_run)

    # Write all.yaml — always overwrite since it's fully auto-generated
    all_yaml_path = chart_dir / "templates" / "all.yaml"
    if dry_run:
        print(f"  [DRY-RUN] Would write: {all_yaml_path}")
    else:
        all_yaml_path.write_text(ALL_YAML_CONTENT)
        print(f"  [WRITE]   {all_yaml_path}")

    # 3. Generate Chart.yaml (always overwrite — version is managed by this script)
    chart_yaml_path = chart_dir / "Chart.yaml"
    write_yaml(chart_yaml_path, build_chart_yaml(app_name, common_version), dry_run)

    # 4. Generate values.yaml (always overwrite — source of truth is apps_definition.yaml)
    values_yaml_path = chart_dir / "values.yaml"
    write_yaml(values_yaml_path, build_values_yaml(app), dry_run)

    # 5. Create images.yaml ONLY if it doesn't exist — CI owns this file after first creation
    images_yaml_path = chart_dir / "images.yaml"
    if not images_yaml_path.exists():
        write_yaml(images_yaml_path, build_images_yaml(), dry_run)
    else:
        print(f"  [SKIP]    {images_yaml_path} (already exists — owned by CI)")


def main(definition_path: Path, output_dir: Path, dry_run: bool) -> None:
    """Entry point: loads app definitions and runs the generator for each app."""
    global CHARTS_DIR, COMMON_LIB_REL

    if not definition_path.exists():
        print(f"ERROR: Definition file not found: {definition_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve output directory and common-lib relative path
    # output_dir is where charts/ will be. 
    # Example: REPO/projects/A/charts
    # COMMON_LIB_PATH: REPO/helm-templates/common-lib
    CHARTS_DIR = output_dir.resolve()
    
    # Calculate depth to get back to repo root from CHARTS_DIR/<app-name>
    # From CHARTS_DIR/<app-name> to CHARTS_DIR is 1 level.
    # From CHARTS_DIR to REPO_ROOT is N levels.
    try:
        # We need relative path from output_dir / "any-app" to COMMON_LIB_PATH
        # Using os.path.relpath is safer for cross-directory relatives
        import os
        dummy_app_path = CHARTS_DIR / "dummy-app"
        COMMON_LIB_REL = os.path.relpath(COMMON_LIB_PATH, dummy_app_path)
    except Exception as e:
        print(f"WARNING: Could not calculate relative path to common-lib: {e}")

    with definition_path.open() as f:
        data = yaml.safe_load(f)

    project = data.get("project", "unknown")
    common_version = data.get("common_version", "1.0.0")
    apps = data.get("apps", [])

    print(f"=== Helm Monorepo Generator ===")
    print(f"Project        : {project}")
    print(f"Common version : {common_version}")
    print(f"Apps to process: {len(apps)}")
    print(f"Dry-run mode   : {dry_run}")
    print(f"Output dir     : {CHARTS_DIR}")
    print(f"Common lib rel : {COMMON_LIB_REL}")

    if not apps:
        print("\nWARNING: No apps found in definition file. Nothing to generate.")
        return

    for app in apps:
        if "name" not in app or "type" not in app:
            print(f"\nERROR: Skipping invalid app entry (missing 'name' or 'type'): {app}", file=sys.stderr)
            continue
        generate_chart(app, common_version, dry_run)

    print(f"\n✅  Done. Generated {len(apps)} chart(s) in {CHARTS_DIR}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Helm Monorepo Generator — scaffolds Helm charts from an apps definition YAML.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Root-level project (default):
  python3 scripts/generator.py

  # One of several sub-projects:
  python3 scripts/generator.py --project ecommerce

  # Dry-run to preview changes without writing files:
  python3 scripts/generator.py --project fintech --dry-run
""",
    )
    parser.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help=(
            "Sub-project name under the projects/ directory. "
            "Auto-sets --definition to projects/NAME/apps_definition.yaml "
            "and --output-dir to projects/NAME/charts/. "
            "Omit to use root-level apps_definition.yaml (single-project mode)."
        ),
    )
    parser.add_argument(
        "--definition",
        type=Path,
        default=None,
        help="Override path to the apps definition YAML file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory for generated charts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing any files.",
    )
    args = parser.parse_args()

    # Resolve paths based on --project shortcut or explicit overrides
    if args.project:
        project_root = REPO_ROOT / "projects" / args.project
        resolved_definition = args.definition or (project_root / "apps_definition.yaml")
        resolved_output = args.output_dir or (project_root / "charts")
    else:
        resolved_definition = args.definition or APPS_DEFINITION_DEFAULT
        resolved_output = args.output_dir or (REPO_ROOT / "charts")

    main(resolved_definition, resolved_output, args.dry_run)
