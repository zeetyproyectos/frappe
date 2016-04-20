# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals, absolute_import
import frappe
from frappe import _
import json
from frappe.core.doctype.user.user import extract_mentions
from frappe.utils import get_fullname, get_link_to_form
from frappe.website.render import clear_cache
from frappe.model.db_schema import add_column

def validate_comment(doc):
	"""Raise exception for more than 50 comments."""
	if not (doc.communication_type=='Comment' and doc.reference_doctype and doc.reference_name):
		return

	if doc.comment_type=="Comment" and "<!-- markdown -->" not in doc.content:
		doc.content += '\n<!-- markdown -->'

def on_trash(doc):
	if doc.communication_type != "Comment":
		return

	if doc.reference_doctype == "Message":
		return

	if (doc.comment_type or "Comment") != "Comment":
		frappe.only_for("System Manager")

	_comments = get_comments_from_parent(doc)
	for c in _comments:
		if c.get("name")==doc.name:
			_comments.remove(c)

	update_comments_in_parent(doc.reference_doctype, doc.reference_name, _comments)

def update_comment_in_doc(doc):
	"""Updates `_comments` (JSON) property in parent Document.
	Creates a column `_comments` if property does not exist.

	`_comments` format

		{
			"comment": [String],
			"by": [user],
			"name": [Comment Document name]
		}"""

	if doc.communication_type != "Comment":
		return

	if doc.reference_doctype and doc.reference_name and doc.content and doc.comment_type=="Comment":
		_comments = get_comments_from_parent(doc)
		updated = False
		for c in _comments:
			if c.get("name")==doc.name:
				c["comment"] = doc.content
				updated = True

		if not updated:
			_comments.append({
				"comment": doc.content,
				"by": doc.sender or doc.owner,
				"name": doc.name
			})
		update_comments_in_parent(doc.reference_doctype, doc.reference_name, _comments)

def notify_mentions(doc):
	if doc.communication_type != "Comment":
		return

	if doc.reference_doctype and doc.reference_name and doc.content and doc.comment_type=="Comment":
		mentions = extract_mentions(doc.content)

		if not mentions:
			return

		sender_fullname = get_fullname(frappe.session.user)
		parent_doc_label = "{0} {1}".format(_(doc.reference_doctype), doc.reference_name)
		subject = _("{0} mentioned you in a comment in {1}").format(sender_fullname, parent_doc_label)
		message = frappe.get_template("templates/emails/mentioned_in_comment.html").render({
			"sender_fullname": sender_fullname,
			"comment": doc,
			"link": get_link_to_form(doc.reference_doctype, doc.reference_name, label=parent_doc_label)
		})

		recipients = [frappe.db.get_value("User", {"enabled": 1, "username": username, "user_type": "System User"})
			for username in mentions]

		frappe.sendmail(
			recipients=recipients,
			sender=frappe.session.user,
			subject=subject,
			message=message,
			bulk=True
		)

def get_comments_from_parent(doc):
	try:
		_comments = frappe.db.get_value(doc.reference_doctype, doc.reference_name, "_comments") or "[]"

	except Exception, e:
		if e.args[0] in (1146, 1054):
			# 1146 = no table
			# 1054 = missing column
			_comments = "[]"

		else:
			raise

	return json.loads(_comments)

def update_comments_in_parent(reference_doctype, reference_name, _comments):
	"""Updates `_comments` property in parent Document with given dict.

	:param _comments: Dict of comments."""
	if not reference_doctype or frappe.db.get_value("DocType", reference_doctype, "issingle"):
		return

	try:
		# use sql, so that we do not mess with the timestamp
		frappe.db.sql("""update `tab%s` set `_comments`=%s where name=%s""" % (reference_doctype,
			"%s", "%s"), (json.dumps(_comments), reference_name))

	except Exception, e:
		if e.args[0] == 1054 and frappe.local.request:
			# missing column and in request, add column and update after commit
			frappe.local._comments = (getattr(frappe.local, "_comments", [])
				+ [(reference_doctype, reference_name, _comments)])

		else:
			raise

	else:
		reference_doc = frappe.get_doc(reference_doctype, reference_name)
		if getattr(reference_doc, "get_route", None):
			clear_cache(reference_doc.get_route())

def add_info_comment(**kwargs):
	kwargs.update({
		"doctype": "Communication",
		"communication_type": "Comment",
		"comment_type": "Info"
	})
	return frappe.get_doc(kwargs).insert(ignore_permissions=True)

def update_comments_in_parent_after_request():
	"""update _comments in parent if _comments column is missing"""
	if hasattr(frappe.local, "_comments"):
		for (reference_doctype, reference_name, _comments) in frappe.local._comments:
			add_column(reference_doctype, "_comments", "Text")
			update_comments_in_parent(reference_doctype, reference_name, _comments)

		frappe.db.commit()
