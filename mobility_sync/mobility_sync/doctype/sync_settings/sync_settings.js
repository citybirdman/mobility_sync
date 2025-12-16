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
                        fieldtype: "Text",
                        label: "Accept URLS",
                        reqd: 1,
                        description: "You can add multiple URLs separated by new lines."
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

            frm.add_custom_button(__("Add Incoming Connected App"), function() {
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

        }
    }
});

frappe.ui.form.on('Sync Settings Apps', {
    connect_app: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.app_name) {
            return;
        }
        frappe.db.exists("Connected App", row.app_name).then(exists => {
            if (exists) {
                // Safe to fetch full doc
                frappe.db.get_doc("Connected App", row.app_name).then(connected_app => {
                    frappe.call({
                        method: "initiate_web_application_flow",
                        doc: connected_app,
                        callback: (r) => {
                            if (r.message) {
                                window.open(r.message, "_blank");
                            }
                        }
                    });
                });
            }
        });
    }
});

frappe.ui.form.on("Sync Settings Detail", {
    choose_apps: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const apps = (frm.doc.apps || [])
        .map(r => r.app_name)
        .filter(Boolean);

        const esc = frappe.utils.escape_html;

        const html = `
            <div class="app-tools">
                <button type="button" class="btn btn-xs btn-default btn-select-all">Select all</button>
                <button type="button" class="btn btn-xs btn-default btn-deselect-all">Deselect all</button>
            </div>

            <div class="app-checkboxes two-col">
                ${apps.length ? apps.map(a => `
                <label class="app-item">
                    <input type="checkbox" class="app-cb" value="${esc(a)}">
                    <span>${esc(a)}</span>
                </label>
                `).join("") : `<div class="text-muted">No apps found.</div>`}
            </div>

            <small class="text-muted app-hint">
                Don't select any App if You want to Apply on all Apps
            </small>

            <style>
                .app-tools{ display:flex; gap:8px; margin-bottom:10px; }
                .two-col{ display:grid; grid-template-columns:1fr 1fr; gap:8px 24px; }
                .two-col .app-item{ display:flex; gap:8px; margin:0; font-weight:400; }
                .app-hint{ display:block; margin-top:10px; }
            </style>
            `;
            
            
            const d = new frappe.ui.Dialog({
        title: "Choose Apps",
        fields: [{ fieldtype: "HTML", fieldname: "apps_html" }],
        primary_action_label: "Log Selected",
        primary_action() {
            const selected = d.$wrapper
            .find('input.app-cb:checked')
            .map((i, el) => el.value)
            .get();
            row.apps = JSON.stringify(selected);
            d.hide();
        },
    });

    d.show();
    d.fields_dict.apps_html.$wrapper.html(html);
    const $w = d.fields_dict.apps_html.$wrapper;
    
    $w.off("click", ".btn-select-all");
    $w.off("click", ".btn-deselect-all");
    
    $w.on("click", ".btn-select-all", () => $w.find("input.app-cb").prop("checked", true));
    $w.on("click", ".btn-deselect-all", () => $w.find("input.app-cb").prop("checked", false));
    
}
})

frappe.ui.form.on('Mobility Sync Field Mapping', {
    document_type: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.document_type) {
            return;
        }
        let grid_row = frm.fields_dict['mapping'].grid.grid_rows_by_docname[row.name];
        frappe.model.with_doctype(row.document_type, () => {
            const fields = frappe.meta.get_docfields(row.document_type).filter(f => {
                // exclude layout fields
                return !["Section Break", "Column Break", "Table", "HTML"].includes(f.fieldtype);
            });
            let valid_fields = fields.filter(df => !df.hidden && !df.system_generated && df.fieldname).map(df=>({
                    label: df.label,
                    value: df.fieldname
                }));
			grid_row.get_field("source_fieldname").set_data(valid_fields);
        });
    }
});