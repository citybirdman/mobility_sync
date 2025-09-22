import frappe
# from frappe.oauth import get_oauth_server
# from oauthlib.oauth2 import FatalClientError, OAuth2Error

# @frappe.whitelist(allow_guest=True)
# def receive_doc(doctype, name, method, data):
#     """Receive synced doc from remote instance (OAuth2 protected)."""

#     # --- validate OAuth2 Bearer token ---
#     try:
#         oauth_server = get_oauth_server()
#         valid, req = oauth_server.verify_request(
#             frappe.request.method,
#             frappe.request.url,
#             frappe.request.headers
#         )
#         if not valid:
#             frappe.local.response["http_status_code"] = 401
#             return {"status": "error", "message": "Invalid or missing access token"}
#     except (OAuth2Error, FatalClientError) as e:
#         frappe.local.response["http_status_code"] = 401
#         return {"status": "error", "message": f"OAuth2 validation failed: {str(e)}"}

#     # --- apply the sync ---
#     try:
#         if method in ("after_insert", "on_update"):
#             if frappe.db.exists(doctype, name):
#                 doc = frappe.get_doc(doctype, name)
#                 doc.update(data)
#                 doc.flags.ignore_mandatory = True
#                 doc.flags.ignore_permissions = True
#                 doc.save()
#             else:
#                 new_doc = frappe.new_doc(doctype)
#                 new_doc.update(data)
#                 new_doc.flags.ignore_mandatory = True
#                 new_doc.flags.ignore_permissions = True
#                 new_doc.insert()

#         elif method == "on_trash":
#             if frappe.db.exists(doctype, name):
#                 frappe.delete_doc(doctype, name, ignore_permissions=True, force=1)

#         frappe.db.commit()
#         return {"status": "success", "message": f"{doctype} {name} synced via {method}"}

#     except Exception as e:
#         frappe.db.rollback()
#         frappe.log_error(frappe.get_traceback(), "Sync Receive Failed")
#         frappe.local.response["http_status_code"] = 500
#         return {"status": "error", "message": str(e)}


@frappe.whitelist()
def setup_outgoing_client(client_name, redirect_uri):
    """Create OAuth Client on this site and store credentials in Sync Settings."""
    client = frappe.new_doc("OAuth Client")
    client.app_name = client_name
    client.client_type = "Confidential"
    client.default_redirect_uri = redirect_uri
    client.redirect_uris = redirect_uri
    client.insert(ignore_permissions=True)

    settings = frappe.get_single("Sync Settings")
    settings.outgoing_client_id = client.client_id
    settings.outgoing_redirect_uri = redirect_uri
    settings.incoming_connected_app = client_name
    settings.outgoing_client_secret = client.get_password("client_secret")

    settings.save(ignore_permissions=True)

    return {"status": "success", "client_id": client.client_id}

@frappe.whitelist()
def setup_incoming_connected_app(app_name, provider_url, client_id, client_secret):
    """Create Connected App on this site and link to Sync Settings."""
    app = frappe.new_doc("Connected App")
    settings = frappe.get_single("Sync Settings")
    app.name = settings.incoming_connected_app
    app.provider_name = app_name
    app.authorization_uri = provider_url + "/api/method/frappe.integrations.oauth2.authorize"
    app.token_uri = provider_url + "/api/method/frappe.integrations.oauth2.get_token"
    app.client_id = client_id
    app.client_secret = client_secret
    app.insert(ignore_permissions=True)

    settings.outgoing_redirect_uri = app.redirect_uri
    settings.save(ignore_permissions=True)

    return {"status": "success", "connected_app": app.name}
