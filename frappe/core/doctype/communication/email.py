# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals, absolute_import
import frappe
import json
from email.utils import formataddr, parseaddr
from frappe.utils import get_url, get_formatted_email, cint, validate_email_add, split_emails
from frappe.utils.file_manager import get_file
from frappe.email.bulk import check_bulk_limit
import frappe.email.smtp
from frappe import _

@frappe.whitelist()
def make(doctype=None, name=None, content=None, subject=None, sent_or_received = "Sent",
	sender=None, recipients=None, communication_medium="Email", send_email=False,
	print_html=None, print_format=None, attachments='[]', ignore_doctype_permissions=False,
	send_me_a_copy=False, cc=None):
	"""Make a new communication.

	:param doctype: Reference DocType.
	:param name: Reference Document name.
	:param content: Communication body.
	:param subject: Communication subject.
	:param sent_or_received: Sent or Received (default **Sent**).
	:param sender: Communcation sender (default current user).
	:param recipients: Communication recipients as list.
	:param communication_medium: Medium of communication (default **Email**).
	:param send_mail: Send via email (default **False**).
	:param print_html: HTML Print format to be sent as attachment.
	:param print_format: Print Format name of parent document to be sent as attachment.
	:param attachments: List of attachments as list of files or JSON string.
	:param send_me_a_copy: Send a copy to the sender (default **False**).
	"""

	is_error_report = (doctype=="User" and name==frappe.session.user and subject=="Error Report")

	if doctype and name and not is_error_report and not frappe.has_permission(doctype, "email", name) and not ignore_doctype_permissions:
		raise frappe.PermissionError("You are not allowed to send emails related to: {doctype} {name}".format(
			doctype=doctype, name=name))

	if not sender:
		sender = get_formatted_email(frappe.session.user)

	comm = frappe.get_doc({
		"doctype":"Communication",
		"subject": subject,
		"content": content,
		"sender": sender,
		"recipients": recipients,
		"cc": cc or None,
		"communication_medium": communication_medium,
		"sent_or_received": sent_or_received,
		"reference_doctype": doctype,
		"reference_name": name
	})
	comm.insert(ignore_permissions=True)

	# needed for communication.notify which uses celery delay
	# if not committed, delayed task doesn't find the communication
	frappe.db.commit()

	if send_email:
		comm.send_me_a_copy = send_me_a_copy
		comm.send(print_html, print_format, attachments, send_me_a_copy=send_me_a_copy)

	return {
		"name": comm.name,
		"emails_not_sent_to": ", ".join(comm.emails_not_sent_to) if hasattr(comm, "emails_not_sent_to") else None
	}

def validate_email(doc):
	"""Validate Email Addresses of Recipients and CC"""
	if not (doc.communication_type=="Communication" and doc.communication_medium == "Email"):
		return

	# validate recipients
	for email in split_emails(doc.recipients):
		validate_email_add(email, throw=True)

	# validate CC
	for email in split_emails(doc.cc):
		validate_email_add(email, throw=True)

def notify(doc, print_html=None, print_format=None, attachments=None,
	recipients=None, cc=None, fetched_from_email_account=False):
	"""Calls a delayed celery task 'sendmail' that enqueus email in Bulk Email queue

	:param print_html: Send given value as HTML attachment
	:param print_format: Attach print format of parent document
	:param attachments: A list of filenames that should be attached when sending this email
	:param recipients: Email recipients
	:param cc: Send email as CC to
	:param fetched_from_email_account: True when pulling email, the notification shouldn't go to the main recipient

	"""
	recipients, cc = get_recipients_and_cc(doc, recipients, cc,
		fetched_from_email_account=fetched_from_email_account)

	doc.emails_not_sent_to = set(doc.all_email_addresses) - set(doc.sent_email_addresses)

	if frappe.flags.in_test:
		# for test cases, run synchronously
		doc._notify(print_html=print_html, print_format=print_format, attachments=attachments,
			recipients=recipients, cc=cc)
	else:
		check_bulk_limit(list(set(doc.sent_email_addresses)))

		from frappe.tasks import sendmail
		sendmail.delay(frappe.local.site, doc.name,
			print_html=print_html, print_format=print_format, attachments=attachments,
			recipients=recipients, cc=cc, lang=frappe.local.lang, session=frappe.local.session)

def _notify(doc, print_html=None, print_format=None, attachments=None,
	recipients=None, cc=None):

	prepare_to_notify(doc, print_html, print_format, attachments)

	frappe.sendmail(
		recipients=(recipients or []) + (cc or []),
		show_as_cc=(cc or []),
		expose_recipients=True,
		sender=doc.sender,
		reply_to=doc.incoming_email_account,
		subject=doc.subject,
		content=doc.content,
		reference_doctype=doc.reference_doctype,
		reference_name=doc.reference_name,
		attachments=doc.attachments,
		message_id=doc.name,
		unsubscribe_message=_("Leave this conversation"),
		bulk=True
	)

def update_parent_status(doc):
	"""Update status of parent document based on who is replying."""
	if doc.communication_type != "Communication":
		return

	parent = doc.get_parent_doc()
	if not parent:
		return

	status_field = parent.meta.get_field("status")

	if status_field and "Open" in (status_field.options or "").split("\n"):
		to_status = "Open" if doc.sent_or_received=="Received" else "Replied"

		if to_status in status_field.options.splitlines():
			parent.db_set("status", to_status)

	parent.notify_update()

def get_recipients_and_cc(doc, recipients, cc, fetched_from_email_account=False):
	doc.all_email_addresses = []
	doc.sent_email_addresses = []
	doc.previous_email_sender = None

	if not recipients:
		recipients = get_recipients(doc, fetched_from_email_account=fetched_from_email_account)

	if not cc:
		cc = get_cc(doc, recipients, fetched_from_email_account=fetched_from_email_account)

	if fetched_from_email_account:
		# email was already sent to the original recipient by the sender's email service
		original_recipients, recipients = recipients, []

		# send email to the sender of the previous email in the thread which this email is a reply to
		if doc.previous_email_sender:
			recipients.append(doc.previous_email_sender)

		# cc that was received in the email
		original_cc = split_emails(doc.cc)

		# don't cc to people who already received the mail from sender's email service
		cc = list(set(cc) - set(original_cc) - set(original_recipients))

	return recipients, cc

def prepare_to_notify(doc, print_html=None, print_format=None, attachments=None):
	"""Prepare to make multipart MIME Email

	:param print_html: Send given value as HTML attachment.
	:param print_format: Attach print format of parent document."""

	if print_format:
		doc.content += get_attach_link(doc, print_format)

	set_incoming_outgoing_accounts(doc)

	if not doc.sender or cint(doc.outgoing_email_account.always_use_account_email_id_as_sender):
		sender_name = (frappe.session.data.full_name
			or doc.outgoing_email_account.name
			or _("Notification"))
		sender_email_id = doc.outgoing_email_account.email_id
		doc.sender = formataddr([sender_name, sender_email_id])

	doc.attachments = []

	if print_html or print_format:
		doc.attachments.append(frappe.attach_print(doc.reference_doctype, doc.reference_name,
			print_format=print_format, html=print_html))

	if attachments:
		if isinstance(attachments, basestring):
			attachments = json.loads(attachments)

		for a in attachments:
			if isinstance(a, basestring):
				# is it a filename?
				try:
					file = get_file(a)
					doc.attachments.append({"fname": file[0], "fcontent": file[1]})
				except IOError:
					frappe.throw(_("Unable to find attachment {0}").format(a))
			else:
				doc.attachments.append(a)

def set_incoming_outgoing_accounts(doc):
	doc.incoming_email_account = doc.outgoing_email_account = None

	if doc.reference_doctype:
		doc.incoming_email_account = frappe.db.get_value("Email Account",
			{"append_to": doc.reference_doctype, "enable_incoming": 1}, "email_id")

		doc.outgoing_email_account = frappe.db.get_value("Email Account",
			{"append_to": doc.reference_doctype, "enable_outgoing": 1},
			["email_id", "always_use_account_email_id_as_sender", "name"], as_dict=True)

	if not doc.incoming_email_account:
		doc.incoming_email_account = frappe.db.get_value("Email Account",
			{"default_incoming": 1, "enable_incoming": 1},  "email_id")

	if not doc.outgoing_email_account:
		doc.outgoing_email_account = frappe.db.get_value("Email Account",
			{"default_outgoing": 1, "enable_outgoing": 1},
			["email_id", "always_use_account_email_id_as_sender", "name"], as_dict=True) or frappe._dict()

def get_recipients(doc, fetched_from_email_account=False):
	"""Build a list of email addresses for To"""
	# [EDGE CASE] doc.recipients can be None when an email is sent as BCC
	recipients = split_emails(doc.recipients)

	if fetched_from_email_account and doc.in_reply_to:
		# add sender of previous reply
		doc.previous_email_sender = frappe.db.get_value("Communication", doc.in_reply_to, "sender")
		recipients.append(doc.previous_email_sender)

	if recipients:
		# exclude email accounts
		exclude = [d[0] for d in
			frappe.db.get_all("Email Account", ["email_id"], {"enable_incoming": 1}, as_list=True)]
		exclude += [d[0] for d in
			frappe.db.get_all("Email Account", ["login_id"], {"enable_incoming": 1}, as_list=True)
			if d[0]]

		recipients = filter_email_list(doc, recipients, exclude)

	return recipients

def get_cc(doc, recipients=None, fetched_from_email_account=False):
	"""Build a list of email addresses for CC"""
	# get a copy of CC list
	cc = split_emails(doc.cc)

	if doc.reference_doctype and doc.reference_name:
		if fetched_from_email_account:
			# if it is a fetched email, add follows to CC
			cc.append(get_owner_email(doc))
			cc += get_assignees(doc)

	if getattr(doc, "send_me_a_copy", False) and doc.sender not in cc:
		cc.append(doc.sender)

	if cc:
		# exclude email accounts, unfollows, recipients and unsubscribes
		exclude = [d[0] for d in
			frappe.db.get_all("Email Account", ["email_id"], {"enable_incoming": 1}, as_list=True)]
		exclude += [d[0] for d in
			frappe.db.get_all("Email Account", ["login_id"], {"enable_incoming": 1}, as_list=True)
			if d[0]]
		exclude += [d[0] for d in frappe.db.get_all("User", ["name"], {"thread_notify": 0}, as_list=True)]
		exclude += [(parseaddr(email)[1] or "").lower() for email in recipients]

		if fetched_from_email_account:
			# exclude sender when pulling email
			exclude += [parseaddr(doc.sender)[1]]

		if doc.reference_doctype and doc.reference_name:
			exclude += [d[0] for d in frappe.db.get_all("Email Unsubscribe", ["email"],
				{"reference_doctype": doc.reference_doctype, "reference_name": doc.reference_name}, as_list=True)]

		cc = filter_email_list(doc, cc, exclude, is_cc=True)

	return cc

def filter_email_list(doc, email_list, exclude, is_cc=False):
	# temp variables
	filtered = []
	email_address_list = []

	for email in list(set(email_list)):
		email_address = (parseaddr(email)[1] or "").lower()
		if not email_address:
			continue

		# this will be used to eventually find email addresses that aren't sent to
		doc.all_email_addresses.append(email_address)

		if (email in exclude) or (email_address in exclude):
			continue

		if is_cc:
			is_user_enabled = frappe.db.get_value("User", email_address, "enabled")
			if is_user_enabled==0:
				# don't send to disabled users
				continue

		# make sure of case-insensitive uniqueness of email address
		if email_address not in email_address_list:
			# append the full email i.e. "Human <human@example.com>"
			filtered.append(email)
			email_address_list.append(email_address)

	doc.sent_email_addresses.extend(email_address_list)

	return filtered

def get_owner_email(doc):
	owner = doc.get_parent_doc().owner
	return get_formatted_email(owner) or owner

def get_assignees(doc):
	return [( get_formatted_email(d.owner) or d.owner ) for d in
		frappe.db.get_all("ToDo", filters={
			"reference_type": doc.reference_doctype,
			"reference_name": doc.reference_name,
			"status": "Open"
		}, fields=["owner"])
	]

def get_attach_link(doc, print_format):
	"""Returns public link for the attachment via `templates/emails/print_link.html`."""
	return frappe.get_template("templates/emails/print_link.html").render({
		"url": get_url(),
		"doctype": doc.reference_doctype,
		"name": doc.reference_name,
		"print_format": print_format,
		"key": doc.get_parent_doc().get_signature()
	})
