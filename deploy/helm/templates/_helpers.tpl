{{- define "xdocs.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "xdocs.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "xdocs.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "xdocs.labels" -}}
app.kubernetes.io/name: {{ include "xdocs.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
