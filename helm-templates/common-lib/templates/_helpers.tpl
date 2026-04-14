{{/*
================================================================================
  common-lib/_helpers.tpl
  Defines shared helper templates used across all applications in the platform.
================================================================================
*/}}

{{/*
  common-lib.name
  Returns the chart name, allowing override via .Values.nameOverride.
*/}}
{{- define "common-lib.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
  common-lib.fullname
  Generates the full resource name: release-name + chart-name (or fullnameOverride).
  Truncated to 63 characters to comply with Kubernetes DNS naming rules.
*/}}
{{- define "common-lib.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
  common-lib.chart
  Returns the "chart-name-chart-version" string used in labels.
*/}}
{{- define "common-lib.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
  common-lib.labels
  Standard recommended labels set per Kubernetes conventions.
  Applied to all resources.
*/}}
{{- define "common-lib.labels" -}}
helm.sh/chart: {{ include "common-lib.chart" . }}
{{ include "common-lib.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
  common-lib.selectorLabels
  Labels used in selector (matchLabels) for Deployments and Services.
  These MUST remain consistent after initial deployment; changing them
  requires deleting and re-creating the resource.
*/}}
{{- define "common-lib.selectorLabels" -}}
app.kubernetes.io/name: {{ include "common-lib.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
  common-lib.serviceAccountName
  Returns the ServiceAccount name from config, or falls back to "default".
*/}}
{{- define "common-lib.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "common-lib.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
