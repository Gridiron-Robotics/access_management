# Deployable image: the official Cerbos PDP with OUR ERP policies + config baked in.
#
# Pinned to an exact Cerbos release for reproducible deploys. Bump deliberately;
# never use a floating tag like ":latest".
#
# To pin even harder (recommended for prod), append the digest, e.g.:
#   FROM ghcr.io/cerbos/cerbos:0.54.0@sha256:<digest>
FROM ghcr.io/cerbos/cerbos:0.54.0

# Bake in the production config and the policy set (the source of truth).
# Both configs ship in the image; CERBOS_CONFIG selects disk (default) or Hub mode.
COPY deploy/kamal/conf.yaml /conf.yaml
COPY deploy/kamal/conf.hub.yaml /conf.hub.yaml
COPY policies /policies

# Tell Cerbos which config to load, and turn off anonymous telemetry.
ENV CERBOS_CONFIG=/conf.yaml
ENV CERBOS_NO_TELEMETRY=1

EXPOSE 3592 3593

# ENTRYPOINT ["/cerbos"] and CMD ["server"] are inherited from the base image.
