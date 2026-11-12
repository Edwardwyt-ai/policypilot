# Local development only: the upstream community repository is archived.
# Build from upstream source without depending on withdrawn MinIO images.
FROM golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS builder
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOBIN=/out
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go install -p=2 github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c
RUN /out/minio --version

FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="7aac2a2c5b7c882e68c1ce017d8256be2feea27f" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /out/minio /usr/local/bin/minio
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
