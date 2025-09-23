// Copyright (c) 2025, Ahmed Zaytoon and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sync Settings", {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Setup Outgoing OAuth Client"), function() {
                frappe.prompt([
                    {
                        fieldname: "client_name",
                        fieldtype: "Data",
                        label: "OAuth Client Name",
                        reqd: 1
                    },
                    {
                        fieldname: "redirect_uri",
                        fieldtype: "Data",
                        label: "Redirect URI",
                        reqd: 1
                    },
                ], (values) => {
                    frappe.call({
                        method: "mobility_sync.sync.api.setup_outgoing_client",
                        args: values,
                        callback: function(r) {
                            frm.reload_doc();
                        }
                    });
                }, __("Create OAuth Client"), __("Create"));
            });

            frm.add_custom_button(__("Setup Incoming Connected App"), function() {
                frappe.prompt([
                    {
                        fieldname: "app_name",
                        fieldtype: "Data",
                        label: "Connected App Name",
                        reqd: 1
                    },
                    {
                        fieldname: "provider_url",
                        fieldtype: "Data",
                        label: "Provider URL",
                        reqd: 1
                    },
                    {
                        fieldname: "client_id",
                        fieldtype: "Data",
                        label: "Client ID",
                        reqd: 1
                    },
                    {
                        fieldname: "client_secret",
                        fieldtype: "Password",
                        label: "Client Secret",
                        reqd: 1
                    }
                ], (values) => {
                    frappe.call({
                        method: "mobility_sync.sync.api.setup_incoming_connected_app",
                        args: values,
                        callback: function(r) {
                            frm.reload_doc();
                            
                        }
                    });
                }, __("Create Connected App"), __("Create"));
            });

            if (frm.doc.incoming_connected_app) {
                frappe.db.exists("Connected App", frm.doc.incoming_connected_app).then(exists => {
                    if (exists) {
                        // Safe to fetch full doc
                        frappe.db.get_doc("Connected App", frm.doc.incoming_connected_app).then(connected_app => {
                            frm.add_custom_button(
                                __("Connect to {0}", [connected_app.provider_name || connected_app.app_name]),
                                () => {
                                    frappe.call({
                                        method: "frappe.integrations.doctype.connected_app.connected_app.initiate_web_application_flow",
                                        args: {
                                            doc: connected_app
                                        },
                                        callback: (r) => {
                                            if (r.message) {
                                                window.open(r.message, "_blank");
                                            }
                                        }
                                    });
                                }
                            );
                        });
                    }
                });
            }


        }
    }
});
