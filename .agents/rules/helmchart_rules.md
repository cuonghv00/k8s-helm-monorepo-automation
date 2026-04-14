---
trigger: manual
---

**1. General Naming and Formatting Rules**
*   **Chart Names:** Chart names must consist of lowercase letters and numbers separated by dashes; avoid uppercase letters, underscores, and dots.
*   **Versioning:** Always use SemVer 2 for version numbers.
*   **YAML Indentation:** Indent all YAML files using exactly **two spaces** and never use tabs.
*   **Namespaces:** **Do not hardcode the `namespace` property** in the `metadata` section of chart templates. Let the user inject the namespace dynamically via the Kubernetes client flag (e.g., `--namespace`).

**2. Template Authoring Rules**
*   **File Naming:** Use the `.yaml` extension for files that output YAML, and `.tpl` for template files that output no formatted content. Use dashed notation for filenames, reflecting the resource kind (e.g., `foo-pod.yaml`).
*   **One Resource Per File:** Each resource definition must reside in its own separate template file.
*   **Namespacing `define` Blocks:** All defined templates are globally accessible, so you must **namespace every defined template name** to prevent conflicts (e.g., use `{{- define "mychart.fullname" -}}` instead of `{{- define "fullname" -}}`).
*   **Whitespace Management:** Include a space after the opening brace and before the closing brace in template directives (e.g., `{{ .foo }}`). Use the chomp modifier (`-`) to minimize blank lines and avoid adjacent empty lines in the generated YAML.
*   **Comments:** Use template comments `{{- /* comment */ -}}` to document the template logic. Only use standard YAML comments (`#`) when the comment is useful for users debugging the rendered output via `helm install --debug`.
*   **JSON in YAML:** You may use JSON syntax for simple lists to improve readability (e.g., `arguments: ["--dirname", "/foo"]`), but avoid using JSON for complex configurations.

**3. Structuring `values.yaml`**
*   **Variable Naming:** Use **camelCase starting with a lowercase letter** for user-defined variables, as Helm's built-in variables start with an uppercase letter.
*   **Flat Over Nested:** Favor a flat configuration structure over deeply nested ones. Flat structures reduce the need to write existence checks at every layer of the template, making the code much easier to read.
*   **Use Maps Instead of Lists:** When users need to override default values using the `--set` flag, lists are error-prone and hard to configure. Always **structure values as maps/dictionaries** instead.
*   **Quote Strings:** Be explicit about strings by quoting them to avoid YAML type coercion issues, such as large integers turning into scientific notation or string booleans converting to actual booleans.
*   **Documentation:** **Document every single property** in `values.yaml`. The comment must begin with the name of the parameter it is describing.

**4. Pods and Workload Configurations**
*   **Image Tags:** Use fixed image tags or SHAs. **Never use floating tags** like `latest`, `head`, or `canary`. Allow users to easily swap images by defining the image name and tag as separate fields in `values.yaml`.
*   **Pull Policies:** Explicitly set the `imagePullPolicy` to `IfNotPresent` by default.
*   **Pod Selectors:** All `PodTemplate` sections (used in Deployments, DaemonSets, etc.) **must declare a `selector`**. This enforces a strict relationship between the set and the pods, preventing breakage if label values change in the future.

**5. Labels, Annotations, and RBAC**
*   **Labels vs. Annotations:** Use labels strictly for identifying resources for Kubernetes queries. If metadata is not meant for querying, use annotations. **Helm hooks must always be configured as annotations**.
*   **Standard Labels:** Always apply standard Helm labels to your resources for global consistency: `app.kubernetes.io/name`, `helm.sh/chart`, `app.kubernetes.io/instance`, and `app.kubernetes.io/managed-by` (which should be set to `{{ .Release.Service }}`).
*   **RBAC Separation:** Define `rbac` and `serviceAccount` configurations under distinct, separate keys in `values.yaml`.
*   **RBAC Defaults:** Set `rbac.create` to `true` by default, allowing users to opt out if they manage access controls themselves. Use helper templates to dynamically generate the ServiceAccount name.

**6. Managing Dependencies and CRDs**
*   **Dependency Versions:** Declare dependency versions using ranges with patch-level matches (e.g., `~1.2.3`), rather than pinning to an exact version. Pre-release versions require appending `-0` (e.g., `~1.2.3-0`).
*   **Repository URLs:** Prioritize `https://` URLs for repositories.
*   **Optional Dependencies:** If a dependency is optional, implement `condition: somechart.enabled` or define shared `tags` so the user can toggle features easily.
*   **CRD Management:** Put Custom Resource Declarations (CRDs) in the special `crds/` directory to ensure they register before the cluster evaluates other resources. Note that **files in the `crds/` folder cannot be templated**, and Helm currently does not support upgrading, deleting, or dry-running CRDs in this folder.
*   **CRD Alternative:** If advanced lifecycle management is needed for CRDs, separate the CRD definitions into their own independent chart, instructing the user to install it before installing the chart that uses those CRDs.