# Copy these additions into your Horilla project. (Reference only — not imported.)

# 1) horilla/settings.py — register the app (place AFTER the INSTALLED_APPS list):
INSTALLED_APPS += ["cerbos_access"]

# Where the Cerbos PDP is reachable FROM Horilla (used by the "Preview access"
# button). In Kamal/Helm this is the access-management service URL.
CERBOS_PDP_URL = env("CERBOS_PDP_URL", default="http://localhost:3592")


# 2) horilla/horilla_apps.py — make the sidebar menu appear (append to SIDEBARS):
# SIDEBARS.append("cerbos_access")


# 3) horilla/urls.py — wire the routes (add to urlpatterns):
# from django.urls import include, path
# urlpatterns += [path("", include("cerbos_access.urls"))]
