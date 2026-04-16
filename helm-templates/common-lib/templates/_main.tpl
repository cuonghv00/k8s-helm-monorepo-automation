{{/*
================================================================================
  common-lib/templates/main.yaml -> renamed to _main.tpl for Helm 4 compatibility
================================================================================
*/}}
{{- define "common-lib.main" -}}
{{- if not .Values.type }}
  {{- fail "ERROR: .Values.type is required. Supported values: deployment" }}
{{- end }}

{{- if and .Values.pvc .Values.pvc.enabled }}
{{ include "common-lib.pvc" . }}
---
{{- end }}

{{- if eq .Values.type "deployment" }}
{{ include "common-lib.deployment" . }}
{{- else }}
  {{- fail (printf "ERROR: Unsupported .Values.type '%s'. Supported values: deployment" .Values.type) }}
{{- end }}

{{- if .Values.service.enabled }}
---
{{ include "common-lib.service" . }}
{{- end }}

{{- if .Values.ingress.enabled }}
---
{{ include "common-lib.ingress" . }}
{{- end }}

{{- end }}
