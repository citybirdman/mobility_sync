import frappe
import requests

# --------------------------------------------------------
# Utilities
# --------------------------------------------------------

def is_doctype_enabled(doctype):
    """Check if given doctype is enabled in Sync Settings (child table)."""
    try:
        settings = frappe.get_single("Sync Settings")
    except frappe.DoesNotExistError:
        return False

    for row in settings.get("doctypes") or []:
        if row.sync_doctype == doctype and row.enabled:
            return True
    return False


def get_oauth_tokens():
    """Fetch or refresh tokens for the connected app."""
    settings = frappe.get_single("Sync Settings")
    if not settings.connected_app or not settings.refresh_token:
        frappe.throw("Sync Settings missing connected app or refresh token")

    connected_app = frappe.get_doc("Connected App", settings.connected_app)

    token_url = f"{connected_app.get('provider_url')}/api/method/frappe.integrations.oauth2.get_token"

    resp = requests.post(token_url, data={
        "grant_type": "refresh_token",
        "refresh_token": settings.refresh_token,
        "client_id": connected_app.client_id,
        "client_secret": connected_app.get_password("client_secret"),
    })

    if resp.status_code != 200:
        frappe.throw(f"Failed to refresh token: {resp.text}")

    tokens = resp.json()
    return tokens.get("access_token")


def push_to_remote(doc, method):
    """Push changes of a document to the remote instance."""
    access_token = get_oauth_tokens()
    settings = frappe.get_single("Sync Settings")
    connected_app = frappe.get_doc("Connected App", settings.connected_app)

    url = f"{connected_app.get('provider_url')}/api/method/mobility_sync.sync.api.receive_doc"

    payload = {
        "doctype": doc.doctype,
        "name": doc.name,
        "method": method,
        "data": doc.as_dict()
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        frappe.log_error(resp.text, "Sync Push Failed")


# --------------------------------------------------------
# Event handler
# --------------------------------------------------------

def handle_doc_event(doc, method):
    """Hook entrypoint for doc_events"""
    if not is_doctype_enabled(doc.doctype):
        return

    push_to_remote(doc, method)
