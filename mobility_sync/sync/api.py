import frappe

@frappe.whitelist(allow_guest=True)
def receive_doc(doctype, name, doc_method, data):
    """Validate OAuth2 Bearer token manually and sync doc."""
    # 1. Extract token
    method = doc_method
    auth_header = frappe.get_request_header("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        frappe.throw("Missing or invalid Authorization header", frappe.PermissionError)

    token = auth_header.split(" ")[1]

    # 2. Check token in DB (Token Cache → OAuth Bearer Token doctype)
    token_info = frappe.db.get_value(
        "OAuth Bearer Token",
        {"access_token": token, "status": "Active"},
        ["client", "user", "scopes", "expires_in"],
        as_dict=True
    )

    if not token_info:
        frappe.throw("Invalid or expired access token", frappe.PermissionError)

    # 3. Optional: check expiry
    from frappe.utils import now_datetime
    if token_info.expires and token_info.expires < now_datetime():
        frappe.throw("Access token expired", frappe.PermissionError)

    # 5. Process doc
    data = frappe._dict(data)
    if method == "after_insert":
        if not frappe.db.exists(doctype, name):
            doc = frappe.get_doc(data)
            doc.insert(ignore_permissions=True)
            if doc.name != name:
                frappe.rename_doc(doctype, doc.name, name, force=True)
    elif method == "on_update":
        if frappe.db.exists(doctype, name):
            doc = frappe.get_doc(doctype, name)

            # Exclude default/system fields
            system_fields = [
                "name", "owner", "creation", "modified", "modified_by",
                "docstatus", "idx", "__unsaved"
            ]

            for key, value in data.items():
                if key not in system_fields:
                    setattr(doc, key, value)

            doc.save(ignore_permissions=True)
    elif method == "on_trash":
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

    frappe.db.commit()
    return {"status": "success", "method": method, "doctype": doctype, "name": name}


@frappe.whitelist()
def setup_outgoing_client(client_name, redirect_uri):
    """Create OAuth Client on this site and store credentials in Sync Settings."""
    uris = redirect_uri.splitlines()
    client = frappe.new_doc("OAuth Client")
    client.app_name = client_name
    client.client_type = "Confidential"
    client.default_redirect_uri = uris[0] + "/api/method/frappe.integrations.doctype.connected_app.connected_app.callback/" + client_name
    client.redirect_uris = " ".join([redirect_uri + "/api/method/frappe.integrations.doctype.connected_app.connected_app.callback/" + client_name for redirect_uri in uris])
    client.insert(ignore_permissions=True)

    settings = frappe.get_single("Sync Settings")
    settings.outgoing_client_id = client.client_id
    settings.outgoing_redirect_uri = redirect_uri
    settings.incoming_connected_app = client_name
    settings.outgoing_client_secret = client.get_password("client_secret")

    settings.save(ignore_permissions=True)

    return {"status": "success", "client_id": client.client_id}

@frappe.whitelist()
def setup_incoming_connected_app(app_name, provider_url, client_id, client_secret, redirect_uri=None):
    """Create Connected App, rename it to a fixed name, and link to Sync Settings."""
    forced_name = frappe.scrub(app_name)
    app_exists = frappe.db.exists("Connected App", forced_name)
    # Step 1: Get The App
    if app_exists:
        app = frappe.get_doc("Connected App", forced_name)
    else:
        app = frappe.new_doc("Connected App")
    app.app_name = app_name
    app.provider_name = app_name
    app.authorization_uri = provider_url.rstrip("/") + "/api/method/frappe.integrations.oauth2.authorize"
    app.token_uri = provider_url.rstrip("/") + "/api/method/frappe.integrations.oauth2.get_token"
    app.client_id = client_id
    app.client_secret = client_secret
    if redirect_uri and hasattr(app, "redirect_uri"):
        app.redirect_uri = redirect_uri
    if app_exists:
        app.save(ignore_permissions=True)
    else:
        app.insert(ignore_permissions=True)

    # Step 2: Rename to forced name
    if app.name != forced_name:
        frappe.rename_doc("Connected App", app.name, forced_name, force=True)
        app = frappe.get_doc("Connected App", forced_name).save(ignore_permissions=True)

    # Step 4: Update Sync Settings
    settings = frappe.get_single("Sync Settings")
    row = next((r for r in settings.apps if r.app_name == forced_name), None)
    if row:
        # update existing row
        row.provider_url = provider_url
        row.client_id = app.client_id
        row.client_secret = app.client_secret
    else:
        # add new row
        settings.append("apps", {
            "provider_url": provider_url,
            "app_name": forced_name,
            "client_id": app.client_id,
            "client_secret": app.client_secret,
        })
    # settings.outgoing_redirect_uri = provider_url
    # settings.incoming_connected_app = forced_name
    settings.flags.ignore_links = True
    settings.flags.ignore_validate = True
    settings.flags.ignore_links = True
    settings.save()

    frappe.db.commit()

    return {"status": "success", "connected_app": forced_name}
