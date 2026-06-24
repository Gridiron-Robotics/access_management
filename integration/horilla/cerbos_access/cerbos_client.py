"""Tiny Cerbos PDP client (CheckResources), used by the 'preview access' feature.

Configure the PDP location in Horilla settings:
    CERBOS_PDP_URL = "http://cerbos:3592"
"""
import requests
from django.conf import settings


def _base_url():
    return getattr(settings, "CERBOS_PDP_URL", "http://localhost:3592").rstrip("/")


def check_resources(principal, resources, request_id="hrms-preview"):
    payload = {"requestId": request_id, "principal": principal, "resources": resources}
    resp = requests.post(f"{_base_url()}/api/check/resources", json=payload, timeout=5)
    resp.raise_for_status()
    return resp.json()
