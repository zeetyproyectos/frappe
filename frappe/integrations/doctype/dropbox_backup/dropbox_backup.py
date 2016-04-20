# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# SETUP:
# install pip install --upgrade dropbox
#
# Create new Dropbox App
#
# in conf.py, set oauth2 settings
# dropbox_access_key
# dropbox_access_secret

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe.utils import cint, split_emails, get_request_site_address, cstr
from frappe.utils.backups import new_backup
from frappe.utils import get_files_path, get_backups_path

import os
from frappe import _

ignore_list = [".DS_Store"]

class DropboxBackup(Document):
	pass

def take_backups_daily():
	take_backups_if("Daily")

def take_backups_weekly():
	take_backups_if("Weekly")

def take_backups_if(freq):
	if cint(frappe.db.get_value("Dropbox Backup", None, "send_backups_to_dropbox")):
		if frappe.db.get_value("Dropbox Backup", None, "upload_backups_to_dropbox")==freq:
			take_backups_dropbox()

@frappe.whitelist()
def take_backups_dropbox():
	did_not_upload, error_log = [], []
	try:
		did_not_upload, error_log = backup_to_dropbox()
		if did_not_upload: raise Exception

		send_email(True, "Dropbox")
	except Exception:
		file_and_error = [" - ".join(f) for f in zip(did_not_upload, error_log)]
		error_message = ("\n".join(file_and_error) + "\n" + frappe.get_traceback())
		frappe.errprint(error_message)
		send_email(False, "Dropbox", error_message)

def send_email(success, service_name, error_status=None):
	if success:
		subject = "Backup Upload Successful"
		message ="""<h3>Backup Uploaded Successfully</h3><p>Hi there, this is just to inform you
		that your backup was successfully uploaded to your %s account. So relax!</p>
		""" % service_name

	else:
		subject = "[Warning] Backup Upload Failed"
		message ="""<h3>Backup Upload Failed</h3><p>Oops, your automated backup to %s
		failed.</p>
		<p>Error message: <br>
		<pre><code>%s</code></pre>
		</p>
		<p>Please contact your system manager for more information.</p>
		""" % (service_name, error_status)

	if not frappe.db:
		frappe.connect()

	recipients = split_emails(frappe.db.get_value("Dropbox Backup", None, "send_notifications_to"))
	frappe.sendmail(recipients=recipients, subject=subject, message=message)

@frappe.whitelist()
def get_dropbox_authorize_url():
	sess = get_dropbox_session()
	request_token = sess.obtain_request_token()
	return_address = get_request_site_address(True) \
		+ "?cmd=frappe.integrations.doctype.dropbox_backup.dropbox_backup.dropbox_callback"

	url = sess.build_authorize_url(request_token, return_address)

	return {
		"url": url,
		"key": request_token.key,
		"secret": request_token.secret,
	}

@frappe.whitelist(allow_guest=True)
def dropbox_callback(oauth_token=None, not_approved=False):
	if not not_approved:
		if frappe.db.get_value("Dropbox Backup", None, "dropbox_access_key")==oauth_token:
			allowed = 1
			message = "Dropbox access allowed."

			sess = get_dropbox_session()
			sess.set_request_token(frappe.db.get_value("Dropbox Backup", None, "dropbox_access_key"),
				frappe.db.get_value("Dropbox Backup", None, "dropbox_access_secret"))
			access_token = sess.obtain_access_token()
			frappe.db.set_value("Dropbox Backup", "Dropbox Backup", "dropbox_access_key", access_token.key)
			frappe.db.set_value("Dropbox Backup", "Dropbox Backup", "dropbox_access_secret", access_token.secret)
			frappe.db.set_value("Dropbox Backup", "Dropbox Backup", "dropbox_access_allowed", allowed)
			frappe.db.set_value("Dropbox Backup", "Dropbox Backup", "send_backups_to_dropbox", 1)
			#dropbox_client = client.DropboxClient(sess)
			# try:
			# 	dropbox_client.file_create_folder("private")
			# 	dropbox_client.file_create_folder("private/files")
			# 	dropbox_client.file_create_folder("files")
			# except:
			# 	pass

		else:
			allowed = 0
			message = "Illegal Access Token Please try again."
	else:
		allowed = 0
		message = "Dropbox Access not approved."

	frappe.local.message_title = "Dropbox Approval"
	frappe.local.message = "<h3>%s</h3><p>Please close this window.</p>" % message

	if allowed:
		frappe.local.message_success = True

	frappe.db.commit()
	frappe.response['type'] = 'page'
	frappe.response['page_name'] = 'message.html'

def backup_to_dropbox():
	if not frappe.db:
		frappe.connect()

	dropbox_client = get_dropbox_client()

	# upload database
	backup = new_backup(ignore_files=True)
	filename = os.path.join(get_backups_path(), os.path.basename(backup.backup_path_db))
	dropbox_client = upload_file_to_dropbox(filename, "/database", dropbox_client)

	frappe.db.close()

	# upload files to files folder
	did_not_upload = []
	error_log = []

	dropbox_client = upload_from_folder(get_files_path(), "/files", dropbox_client, did_not_upload, error_log)
	dropbox_client = upload_from_folder(get_files_path(is_private=1), "/private/files", dropbox_client, did_not_upload, error_log)

	frappe.connect()
	return did_not_upload, list(set(error_log))

def get_dropbox_client(previous_dropbox_client=None):
	from dropbox import client

	sess = get_dropbox_session()

	sess.set_token(frappe.db.get_value("Dropbox Backup", None, "dropbox_access_key"),
		frappe.db.get_value("Dropbox Backup", None, "dropbox_access_secret"))

	dropbox_client = client.DropboxClient(sess)

	# upgrade to oauth2
	token = dropbox_client.create_oauth2_access_token()
	dropbox_client = client.DropboxClient(token)

	if previous_dropbox_client:
		dropbox_client.connection_reset_count = previous_dropbox_client.connection_reset_count + 1
	else:
		dropbox_client.connection_reset_count = 0

	return dropbox_client

def upload_from_folder(path, dropbox_folder, dropbox_client, did_not_upload, error_log):
	import dropbox.rest

	if not os.path.exists(path):
		return

	try:
		response = dropbox_client.metadata(dropbox_folder)
	except dropbox.rest.ErrorResponse, e:
		# folder not found
		if e.status==404:
			response = {"contents": []}
		else:
			raise

	for filename in os.listdir(path):
		filename = cstr(filename)

		if filename in ignore_list:
			continue

		found = False
		filepath = os.path.join(path, filename)
		for file_metadata in response["contents"]:
 			if os.path.basename(filepath) == os.path.basename(file_metadata["path"]) and os.stat(filepath).st_size == int(file_metadata["bytes"]):
				found = True
				break

		if not found:
			try:
				dropbox_client = upload_file_to_dropbox(filepath, dropbox_folder, dropbox_client)
			except Exception:
				did_not_upload.append(filename)
				error_log.append(frappe.get_traceback())

	return dropbox_client

def get_dropbox_session():
	try:
		from dropbox import session
	except:
		frappe.msgprint(_("Please install dropbox python module"), raise_exception=1)

	if not (frappe.conf.dropbox_access_key or frappe.conf.dropbox_secret_key):
		frappe.throw(_("Please set Dropbox access keys in your site config"))

	sess = session.DropboxSession(frappe.conf.dropbox_access_key, frappe.conf.dropbox_secret_key, "app_folder")
	return sess

def upload_file_to_dropbox(filename, folder, dropbox_client):
	from dropbox import rest
	size = os.stat(filename).st_size

	with open(filename, 'r') as f:
		# if max packet size reached, use chunked uploader
		max_packet_size = 4194304

		if size > max_packet_size:
			uploader = dropbox_client.get_chunked_uploader(f, size)
			while uploader.offset < size:
				try:
					uploader.upload_chunked()
					uploader.finish(folder + "/" + os.path.basename(filename), overwrite=True)

				except rest.ErrorResponse, e:
					# if "[401] u'Access token not found.'",
					# it means that the user needs to again allow dropbox backup from the UI
					# so re-raise

					if (e.startswith("[401]")
						and dropbox_client.connection_reset_count < 10
						and e != "[401] u'Access token not found.'"):

						# session expired, so get a new connection!
						# [401] u"The given OAuth 2 access token doesn't exist or has expired."
						dropbox_client = get_dropbox_client(dropbox_client)

					else:
						raise
		else:
			dropbox_client.put_file(folder + "/" + os.path.basename(filename), f, overwrite=True)

	return dropbox_client

if __name__=="__main__":
	backup_to_dropbox()
