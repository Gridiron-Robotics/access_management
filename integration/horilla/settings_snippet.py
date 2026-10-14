# Copy these additions into your Horilla project. (Reference only — not imported.)

# 1) horilla/settings.py — register the app (place AFTER the INSTALLED_APPS list):
INSTALLED_APPS += ["cerbos_access"]

# Where the Cerbos PDP is reachable FROM Horilla (used by the "Preview access"
# button). In Kamal/Helm this is the access-management service URL.
CERBOS_PDP_URL = env("CERBOS_PDP_URL", default="http://localhost:3592")

# Keycloak realm-role sync (cerbos_access/keycloak_sync.py). Read straight from
# the process environment — nothing to add here, just set them in the deploy:
#   KEYCLOAK_ADMIN_URL            https://sso.example.com
#   KEYCLOAK_ADMIN_REALM          erp   (default)
#   KEYCLOAK_ADMIN_CLIENT_ID      service-account client (manage-users + view-realm only)
#   KEYCLOAK_ADMIN_CLIENT_SECRET  from your secret store; never commit it
# Leave them unset and the sync is a logged no-op on save.


# 2) horilla/horilla_apps.py — make the sidebar menu appear (append to SIDEBARS):
# SIDEBARS.append("cerbos_access")


# 3) horilla/urls.py — wire the routes (add to urlpatterns):
# from django.urls import include, path
# urlpatterns += [path("", include("cerbos_access.urls"))]
