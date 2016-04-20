# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals, absolute_import
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_add, get_fullname, strip_html
from frappe.model.db_schema import add_column
from frappe.core.doctype.communication.comment import validate_comment, notify_mentions, update_comment_in_doc
from frappe.core.doctype.communication.email import validate_email, notify, _notify, update_parent_status

exclude_from_linked_with = True

class Communication(Document):
	no_feed_on_delete = True

	"""Communication represents an external communication like Email."""

	def validate(self):
		if self.reference_doctype and self.reference_name:
			if not self.reference_owner:
				self.reference_owner = frappe.db.get_value(self.reference_doctype, self.reference_name, "owner")

			# prevent communication against a child table
			if frappe.get_meta(self.reference_doctype).istable:
				frappe.throw(_("Cannot create a {0} against a child document: {1}")
					.format(_(self.communication_type), _(self.reference_doctype)))

		if not self.user:
			self.user = frappe.session.user

		if not self.subject:
			self.subject = strip_html((self.content or "")[:141])

		if not self.sent_or_received:
			self.sent_or_received = "Sent"

		self.set_status()
		self.set_sender_full_name()
		validate_email(self)
		validate_comment(self)
		self.set_timeline_doc()

	def after_insert(self):
		if not (self.reference_doctype and self.reference_name):
			return

		if self.communication_type in ("Communication", "Comment"):
			# send new comment to listening clients
			frappe.publish_realtime('new_communication', self.as_dict(),
				doctype= self.reference_doctype, docname = self.reference_name,
				after_commit=True)

			if self.communication_type == "Comment":
				notify_mentions(self)

		elif self.communication_type in ("Chat", "Notification"):
			if self.reference_name == frappe.session.user:
				message = self.as_dict()
				message['broadcast'] = True
				frappe.publish_realtime('new_message', message, after_commit=True)
			else:
				# reference_name contains the user who is addressed in the messages' page comment
				frappe.publish_realtime('new_message', self.as_dict(),
					user=self.reference_name, after_commit=True)

	def on_update(self):
		"""Update parent status as `Open` or `Replied`."""
		update_parent_status(self)
		update_comment_in_doc(self)

	def on_trash(self):
		if (not self.flags.ignore_permissions
			and self.communication_type=="Comment" and self.comment_type != "Comment"):

			# prevent deletion of auto-created comments if not ignore_permissions
			frappe.throw(_("Sorry! You cannot delete auto-generated comments"))

		if self.communication_type in ("Communication", "Comment"):
			# send delete comment to listening clients
			frappe.publish_realtime('delete_communication', self.as_dict(),
				doctype= self.reference_doctype, docname = self.reference_name,
				after_commit=True)

	def set_status(self):
		if not self.is_new():
			return

		if self.reference_doctype and self.reference_name:
			self.status = "Linked"
		elif self.communication_type=="Communication":
			self.status = "Open"
		else:
			self.status = "Closed"

	def set_sender_full_name(self):
		if not self.sender_full_name and self.sender:
			if self.sender == "Administrator":
				self.sender_full_name = self.sender
				self.sender = frappe.db.get_value("User", "Administrator", "email")
			else:
				validate_email_add(self.sender, throw=True)
				self.sender_full_name = get_fullname(self.sender)

	def get_parent_doc(self):
		"""Returns document of `reference_doctype`, `reference_doctype`"""
		if not hasattr(self, "parent_doc"):
			if self.reference_doctype and self.reference_name:
				self.parent_doc = frappe.get_doc(self.reference_doctype, self.reference_name)
			else:
				self.parent_doc = None
		return self.parent_doc

	def set_timeline_doc(self):
		"""Set timeline_doctype and timeline_name"""
		parent_doc = self.get_parent_doc()
		if (self.timeline_doctype and self.timeline_name) or not parent_doc:
			return

		timeline_field = parent_doc.meta.timeline_field
		if not timeline_field:
			return

		doctype = parent_doc.meta.get_link_doctype(timeline_field)
		name = parent_doc.get(timeline_field)

		if doctype and name:
			self.timeline_doctype = doctype
			self.timeline_name = name

		else:
			return

	def send(self, print_html=None, print_format=None, attachments=None,
		send_me_a_copy=False, recipients=None):
		"""Send communication via Email.

		:param print_html: Send given value as HTML attachment.
		:param print_format: Attach print format of parent document."""

		self.send_me_a_copy = send_me_a_copy
		self.notify(print_html, print_format, attachments, recipients)

	def notify(self, print_html=None, print_format=None, attachments=None,
		recipients=None, cc=None, fetched_from_email_account=False):
		"""Calls a delayed celery task 'sendmail' that enqueus email in Bulk Email queue

		:param print_html: Send given value as HTML attachment
		:param print_format: Attach print format of parent document
		:param attachments: A list of filenames that should be attached when sending this email
		:param recipients: Email recipients
		:param cc: Send email as CC to
		:param fetched_from_email_account: True when pulling email, the notification shouldn't go to the main recipient

		"""
		notify(self, print_html, print_format, attachments, recipients, cc, fetched_from_email_account)

	def _notify(self, print_html=None, print_format=None, attachments=None,
		recipients=None, cc=None):

		_notify(self, print_html, print_format, attachments, recipients, cc)

def on_doctype_update():
	"""Add index in `tabCommunication` for `(reference_doctype, reference_name)`"""
	frappe.db.add_index("Communication", ["reference_doctype", "reference_name"])
	frappe.db.add_index("Communication", ["timeline_doctype", "timeline_name"])

def has_permission(doc, ptype, user):
	if ptype=="read" and doc.reference_doctype and doc.reference_name:
		if frappe.has_permission(doc.reference_doctype, ptype="read", doc=doc.reference_name):
			return True
