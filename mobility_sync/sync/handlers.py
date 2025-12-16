import frappe
import requests
import time
import json
from frappe.utils import get_traceback
from datetime import date, datetime, timedelta
from frappe.utils.background_jobs import get_queue


# --------------------------------------------------------
# Utilities
# --------------------------------------------------------

def convert_properties(doc):
    mapping = frappe.get_all("Mobility Sync Field Mapping", {"document_type": doc.get("doctype")}, ["source_fieldname", "target_fieldname", "exclude"])
    
    if not mapping:
        return doc

    converted = doc.copy()

    for rule in mapping:
        source = rule.get("source_fieldname")
        target = rule.get("target_fieldname")
        exclude = rule.get("exclude")

        if not source:
            continue

        if exclude:
            converted.pop(source, None)
            continue

        if target and source in converted:
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

def is_refresh_job_pending(app_name: str, queue_name: str = "long") -> bool:
    job_id = f"refresh_oauth_token::{app_name}"
    q = get_queue(queue_name)

    job = q.fetch_job(job_id)
    if not job:
        return False

    return job.get_status() in {"queued", "started", "deferred", "scheduled"}

def get_apps(setting_doc):
    if not setting_doc.get("apps"):
        return frappe.get_all("Sync Settings Apps", fields=["app_name"], pluck="app_name")
    return json.loads(setting_doc.get("apps"))

def get_oauth_tokens(app_name):
    """
    Return a valid access_token from the Token Cache (Connected App).
    If expired, enqueue token refresh to avoid DB locks.
    """
    # to be removed later
    # settings = frappe.get_single("Sync Settings")
    # connected_app_name = settings.incoming_connected_app

    token_cache_list = frappe.get_all(
        "Token Cache",
        filters={"connected_app": app_name},
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
        if not is_refresh_job_pending(app_name):
            frappe.enqueue(
                "mobility_sync.sync.handlers.refresh_oauth_token",
                connected_app_name=app_name,
                queue="long",
                job_id= f"refresh_oauth_token::{app_name}",
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
                frappe.log_error(message = resp.text, title = "Token Refresh Failed")
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
                frappe.log_error(message = get_traceback(), title = "Token Refresh Failed After Retry")
                return

def update_queue_record(doc, app_name, success, doc_method="after_insert"):
    if queue_record_name := frappe.db.exists(
        "Mobility Sync Failed Queue", 
        {
            "document_type": doc.get("doctype"),
            "document_name": doc.get("name"),
            "app_name": app_name,
            "doc_method": doc_method,
            "sync_tried": 0
        }):
        queue_doc = frappe.get_doc("Mobility Sync Failed Queue", queue_record_name)
    else:
        queue_doc = None
    if not success:
        if queue_doc:
            queue_doc.sync_tried = 1
            queue_doc.retry_success = 0
            queue_doc.save(ignore_permissions=True)
        frappe.get_doc({
            "doctype": "Mobility Sync Failed Queue",
            "document_type": doc.get("doctype"),
            "document_name": doc.get("name"),
            "app_name": app_name,
            "doc_method": doc_method,
            "sync_tried": 0,
            "retry_success": 0
        }).insert(ignore_permissions=True)
    else:
        if queue_doc:
            queue_doc.sync_tried = 1
            queue_doc.retry_success = 1
            queue_doc.save(ignore_permissions=True)
    frappe.db.commit()

# --------------------------------------------------------
# Sync Push
# --------------------------------------------------------

def push_to_remote(doc, doc_method, max_retries=1, retry_delay=5, app_name=None):
    """Push changes of a document to the remote instance asynchronously with retry."""
    setting_name = frappe.db.get_value(
        "Sync Settings Detail",
        {"parent": "Sync Settings", "sync_doctype": doc.get("doctype")},
        "name"
    )
    if not setting_name:
        return
    settings = frappe.get_doc("Sync Settings Detail", setting_name)
    if not app_name:
        apps = get_apps(settings)
    else:
        apps = [app_name]
    for app in apps:
        access_token = get_oauth_tokens(app)
        if not access_token:
            frappe.log_error(f"Access token not available for app {app}", "Sync Push Failed")
            update_queue_record(doc, app, False, doc_method)
            time.sleep(retry_delay)
            continue

        target_url = frappe.db.get_value("Sync Settings Apps", {"parent": "Sync Settings", "app_name": app}, "provider_url").rstrip("/")
        url = f"{target_url}/api/method/mobility_sync.sync.api.receive_doc"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = convert_dates(doc)
        data = convert_properties(data)
        payload = {
            "doctype": doc.get("doctype"),
            "name": doc.get("name"),
            "doc_method": doc_method,
            "data": data
        }

        retries = 0
        success = True
        while retries < max_retries:
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    success = True
                    break  # Success
                else:
                    frappe.log_error(message = resp.text, title = f"Sync Push Failed ({resp.status_code})")
                    success = False
            except Exception:
                frappe.log_error(message = get_traceback(), title = "Sync Push Exception")
                success = False

            retries += 1
            if retries < max_retries:
                time.sleep(retry_delay)  # Wait before next retry
        
        update_queue_record(doc, app, success, doc_method)



# --------------------------------------------------------
# Event handler
# --------------------------------------------------------

def handle_doc_event(doc, method):
    """Hook entrypoint for doc_events"""
    if not is_doctype_enabled(doc.doctype):
        return
    # Enqueue push to remote to avoid DB locks
    frappe.enqueue(
        "mobility_sync.sync.handlers.push_to_remote",
        doc=doc.as_dict(),
        doc_method=method,
        queue="long",
        timeout=300
    )

def handle_failed_queues():
    """Process failed sync queues."""
    failed_queues = frappe.get_all(
        "Mobility Sync Failed Queue",
        filters={"sync_tried": 0},
        fields=["document_type", "document_name", "app_name"],
        limit=0
    )

    for queue in failed_queues:
        doc = frappe.get_doc(queue.document_type, queue.document_name)
        frappe.enqueue(
            "mobility_sync.sync.handlers.push_to_remote",
            doc=doc.as_dict(),
            doc_method=queue.doc_method,
            app_name=queue.app_name,
            queue="long",
            timeout=300
        )