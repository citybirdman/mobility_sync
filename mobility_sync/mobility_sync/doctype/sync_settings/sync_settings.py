# Copyright (c) 2025, Ahmed Zaytoon and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SyncSettings(Document):
	pass

@frappe.whitelist()
def get_fields_for_doctype(doctype, txt=None, searchfield=None, start=0, page_len=20, filters=None):
    if not filters or not filters.get('document_name'):
        return []

    document_name = filters.get('document_name')
    meta = frappe.get_meta(document_name)

    fields = []
    for df in meta.fields:
        if df.fieldname and not df.hidden:
            fields.append([df.fieldname])

    # Support autocomplete filtering
    if txt:
        fields = [f for f in fields if txt.lower() in f[0].lower()]

    return fields
