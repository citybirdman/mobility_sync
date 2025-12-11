import frappe
import requests
from frappe.utils import get_traceback, now_datetime
from datetime import date, datetime, timedelta

# --------------------------------------------------------
# Utilities
# --------------------------------------------------------

def convert_properties(doc, mapping=None):
    """Convert document properties based on mapping rules."""
    if not mapping:
        return doc
    if not mapping.get("document_type") == doc.get("doctype"):
        return doc
    converted = doc.copy()
    for rule in mapping:
        source = rule.get("source_fieldname")
        target = rule.get("target_fieldname")
        exclude = rule.get("exclude")
        if exclude:
            converted.pop(source)
        if source in converted:
            converted[target] = converted.pop(source)
    return converted

def convert_dates(obj):
    if isinstance(obj, dict):
        return {k: convert_dates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_dates(v) for v in obj]
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    else:
        return obj

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
    """
    Return a valid access_token from the Token Cache (Connected App).
    If expired, enqueue token refresh to avoid DB locks.
    """
    settings = frappe.get_single("Sync Settings")
    connected_app_name = settings.incoming_connected_app

    token_cache_list = frappe.get_all(
        "Token Cache",
        filters={"connected_app": connected_app_name},
        fields=["name", "access_token", "refresh_token", "expires_in", "creation"],
        limit=1,
        order_by="creation desc"
    )

    if not token_cache_list:
        return None

    token_doc = frappe.get_doc("Token Cache", token_cache_list[0].name)
    expires_in = token_doc.expires_in or 0
    created_at = token_doc.creation

    # Check expiration
    if expires_in and (datetime.now() > created_at + timedelta(seconds=expires_in)):
        # Enqueue token refresh in separate transaction
        frappe.enqueue(
            "mobility_sync.sync.handlers.refresh_oauth_token",
            connected_app_name=connected_app_name,
            queue="long",
            timeout=120
        )

    return token_doc.get_password("access_token")


def refresh_oauth_token(connected_app_name):
    """Refresh OAuth token in a separate transaction to avoid locks."""
    retries = 3
    while retries > 0:
        try:
            token_cache_list = frappe.get_all(
                "Token Cache",
                filters={"connected_app": connected_app_name},
                fields=["name", "access_token", "refresh_token", "expires_in", "creation"],
                limit=1,
                order_by="creation desc"
            )
            if not token_cache_list:
                return

            token_doc = frappe.get_doc("Token Cache", token_cache_list[0].name)
            refresh_token = token_doc.get_password("refresh_token")
            if not refresh_token:
                return

            connected_app = frappe.get_doc("Connected App", connected_app_name)
            refresh_url = connected_app.token_uri

            resp = requests.post(refresh_url, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": connected_app.client_id,
                "client_secret": connected_app.client_secret,
            }, timeout=30)

            if resp.status_code != 200:
                frappe.log_error(resp.text[:5000], "Token Refresh Failed")
                return

            tokens = resp.json()

            # Update token cache without row locks
            frappe.db.begin()
            frappe.db.sql("""
                UPDATE `tabToken Cache`
                SET access_token=%s,
                    refresh_token=COALESCE(%s, refresh_token),
                    expires_in=COALESCE(%s, expires_in)
                WHERE name=%s
            """, (tokens.get("access_token"), tokens.get("refresh_token"),
                  tokens.get("expires_in"), token_doc.name))
            frappe.db.commit()
            return

        except Exception:
            frappe.db.rollback()
            retries -= 1
            if retries == 0:
                frappe.log_error(get_traceback()[:5000], "Token Refresh Failed After Retry")
                return


# --------------------------------------------------------
# Sync Push
# --------------------------------------------------------

def push_to_remote(doc, doc_method, max_retries=3, retry_delay=5):
    """Push changes of a document to the remote instance asynchronously with retry."""
    access_token = get_oauth_tokens()
    if not access_token:
        frappe.log_error("Access token not available", "Sync Push Failed")
        return

    settings = frappe.get_single("Sync Settings")
    target_url = settings.outgoing_redirect_uri.rstrip("/")
    url = f"{target_url}/api/method/mobility_sync.sync.api.receive_doc"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = convert_dates(doc)
    data = convert_properties(doc, settings.mapping)
    payload = {
        "doctype": doc.get("doctype"),
        "name": doc.get("name"),
        "doc_method": doc_method,
        "data": convert_dates(doc)
    }

    retries = 0
    while retries < max_retries:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                return  # Success, exit function
            else:
                frappe.log_error(resp.text[:5000], f"Sync Push Failed ({resp.status_code})")
        except Exception:
            frappe.log_error(get_traceback()[:5000], "Sync Push Exception")

        retries += 1
        if retries < max_retries:
            time.sleep(retry_delay)  # Wait before next retry



# --------------------------------------------------------
# Event handler
# --------------------------------------------------------

def handle_doc_event(doc, method):
    """Hook entrypoint for doc_events"""
    if not is_doctype_enabled(doc.doctype):
        return
    # frappe.throw(str(doc.as_dict()))
    # Enqueue push to remote to avoid DB locks
    frappe.enqueue(
        "mobility_sync.sync.handlers.push_to_remote",
        doc=doc.as_dict(),
        doc_method=method,
        queue="long",
        timeout=300
    )
