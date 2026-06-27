#!/usr/bin/env bash
# Create the media bucket on an existing MinIO/S3-compatible endpoint.
#
#   MINIO_ENDPOINT=http://localhost:9000 MINIO_ROOT_USER=minioadmin \
#   MINIO_ROOT_PASSWORD=secret MINIO_BUCKET=xdocs-media ./scripts/init-minio.sh
#
# Requires the MinIO client `mc` (https://min.io/docs/minio/linux/reference/minio-mc.html).
set -euo pipefail

ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
USER="${MINIO_ROOT_USER:-minioadmin}"
PASS="${MINIO_ROOT_PASSWORD:-minioadmin}"
BUCKET="${MINIO_BUCKET:-xdocs-media}"

mc alias set xdocs "${ENDPOINT}" "${USER}" "${PASS}"
mc mb --ignore-existing "xdocs/${BUCKET}"
echo "Bucket '${BUCKET}' ready at ${ENDPOINT}."
