frappe.listview_settings['Bulk Email'] = {
	get_indicator: function(doc) {
		colour = {'Sent': 'green', 'Sending': 'blue', 'Not Sent': 'grey', 'Error': 'red', 'Expired': 'orange'};
		return [__(doc.status), colour[doc.status], "status,=," + doc.status];
	}
}
