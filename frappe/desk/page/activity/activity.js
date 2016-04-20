// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: See license.txt

frappe.provide("frappe.activity");

frappe.pages['activity'].on_page_load = function(wrapper) {
	var me = this;

	frappe.require('assets/frappe/js/lib/flot/jquery.flot.js');
	frappe.require('assets/frappe/js/lib/flot/jquery.flot.downsample.js');

	frappe.ui.make_app_page({
		parent: wrapper,
		single_column: true
	});

	this.page = wrapper.page;

	this.page.set_title(__("Activity"));

	frappe.model.with_doctype("Communication", function() {
		me.page.list = new frappe.ui.Listing({
			hide_refresh: true,
			page: me.page,
			method: 'frappe.desk.page.activity.activity.get_feed',
			parent: $("<div></div>").appendTo(me.page.main),
			render_row: function(row, data) {
				new frappe.activity.Feed(row, data);
			},
			show_filters: true,
			doctype: "Communication",
 			get_args: function() {
				if (frappe.route_options && frappe.route_options.show_likes) {
					delete frappe.route_options.show_likes;
					return {
						show_likes: true
					}
				} else {
					return {}
				}
			}
		});

		me.page.list.run();

		me.page.set_primary_action(__("Refresh"), function() {
			me.page.list.filter_list.clear_filters();
			me.page.list.run();
		}, "octicon octicon-sync");
	});

	frappe.activity.render_plot(this.page);

	this.page.main.on("click", ".activity-message", function() {
		var link_doctype = $(this).attr("data-link-doctype"),
			link_name = $(this).attr("data-link-name"),
			doctype = $(this).attr("data-doctype"),
			docname = $(this).attr("data-docname");

		if (doctype && docname) {
			if (link_doctype && link_name) {
				frappe.route_options = {
					scroll_to: { "doctype": doctype, "name": docname }
				}
			}

			frappe.set_route(["Form", link_doctype || doctype, link_name || docname]);
		}
	});

	// Build Report Button
	if(frappe.boot.user.can_get_report.indexOf("Feed")!=-1) {
		this.page.add_menu_item(__('Build Report'), function() {
			frappe.set_route('Report', "Feed");
		}, 'icon-th')
	}

	this.page.add_menu_item(__('Show Likes'), function() {
		frappe.route_options = {
			show_likes: true
		};
		me.page.list.run();
	}, 'octicon octicon-heart');
};

frappe.pages['activity'].on_page_show = function() {
	frappe.breadcrumbs.add("Desk");
}

frappe.activity.last_feed_date = false;
frappe.activity.Feed = Class.extend({
	init: function(row, data) {
		this.scrub_data(data);
		this.add_date_separator(row, data);
		if(!data.add_class)
			data.add_class = "label-default";

		data.link = "";
		if (data.link_doctype && data.link_name) {
			data.link = frappe.format(data.link_name, {fieldtype: "Link", options: data.link_doctype},
				{label: __(data.link_doctype) + " " + __(data.link_name)});

		} else if (data.feed_type==="Comment" && data.comment_type==="Comment") {
			// hack for backward compatiblity
			data.link_doctype = data.reference_doctype;
			data.link_name = data.reference_name;
			data.reference_doctype = "Communication";
			data.reference_name = data.name;

			data.link = frappe.format(data.link_name, {fieldtype: "Link", options: data.link_doctype},
				{label: __(data.link_doctype) + " " + __(data.link_name)});

		} else if (data.reference_doctype && data.reference_name) {
			data.link = frappe.format(data.reference_name, {fieldtype: "Link", options: data.reference_doctype},
				{label: __(data.reference_doctype) + " " + __(data.reference_name)});
		}

		$(row)
			.append(frappe.render_template("activity_row", data))
			.find("a").addClass("grey");
	},
	scrub_data: function(data) {
		data.by = frappe.user.full_name(data.owner);
		data.imgsrc = frappe.utils.get_file_link(frappe.user_info(data.owner).image);

		data.icon = "icon-flag";
		// if(data.doc_type) {
		// 	data.feed_type = data.doc_type;
		// 	data.icon = frappe.boot.doctype_icons[data.doc_type];
		// }

		// data.feed_type = data.feed_type || "Comment";

		// color for comment
		data.add_class = {
			"Comment": "label-danger",
			"Assignment": "label-warning",
			"Login": "label-default"
		}[data.comment_type || data.communication_medium] || "label-info"

		data.when = comment_when(data.creation);
		data.feed_type = data.comment_type || data.communication_medium;
	},
	add_date_separator: function(row, data) {
		var date = dateutil.str_to_obj(data.creation);
		var last = frappe.activity.last_feed_date;

		if((last && dateutil.obj_to_str(last) != dateutil.obj_to_str(date)) || (!last)) {
			var diff = dateutil.get_day_diff(dateutil.get_today(), dateutil.obj_to_str(date));
			if(diff < 1) {
				pdate = 'Today';
			} else if(diff < 2) {
				pdate = 'Yesterday';
			} else {
				pdate = dateutil.global_date_format(date);
			}
			data.date_sep = pdate;
			data.date_class = pdate=='Today' ? "date-indicator blue" : "date-indicator";
		} else {
			data.date_sep = null;
			data.date_class = "";
		}
		frappe.activity.last_feed_date = date;
	}
});

frappe.activity.render_plot = function(page) {
	page.plot_wrapper = $('<div class="plot-wrapper"><div class="plot"></div></div>')
		.prependTo(page.main)
		.find(".plot");

	frappe.call({
		method: "frappe.desk.page.activity.activity.get_months_activity",
		callback: function(r) {
			var plot_data = [{
				data: $.map(r.message, function(v, i) {
					var d = dateutil.str_to_obj(v[0]);
					return [[d.getTime(), v[1]]];
				})
			}];

			var plot_options = frappe.activity.get_plot_options();

			page.plot = $.plot(page.plot_wrapper.empty(), plot_data, plot_options);

			frappe.activity.setup_plot_hover(page);
		}
	});
};

frappe.activity.get_plot_options = function(data) {
	return {
		grid: {
			hoverable: true,
			clickable: true,
			borderWidth: 1,
			borderColor: "#d1d8dd"
		},
		xaxis: {
			mode: "time",
			timeformat: "%d-%b",
			minTickSize: [1, "day"],
			monthNames: [__("Jan"), __("Feb"), __("Mar"), __("Apr"), __("May"), __("Jun"),
				__("Jul"), __("Aug"), __("Sep"), __("Oct"), __("Nov"), __("Dec")],
			tickLength: 0
		},
		yaxis: {tickLength: 0},
		series: {
			downsample: { threshold: 1000 },
			bars: {
				show: true,
				fill: true,
				barWidth: 43200000,
				align: "center",
				fillColor: "#FCF8E3"
			}
		},
		colors: ["#ffa00a"]
	}
};

frappe.activity.setup_plot_hover = function(page) {
	var tooltip_id = frappe.dom.set_unique_id();

	function showTooltip(x, y, contents) {
		$('<div id="' + tooltip_id + '" class="small">' + contents + '</div>').css( {
			position: 'absolute',
			display: 'none',
			top: y - 30,
			left: x - 10,
			border: '1px solid #ffa00a',
			padding: '2px',
			'background-color': '#ffa00a',
			color: "#FCF8E3"
		}).appendTo("body").fadeIn(200);
	}

	previousPoint = null;
	page.plot_wrapper.bind("plothover", function (event, pos, item) {
		if (item) {
			if (previousPoint != item.dataIndex) {
				previousPoint = item.dataIndex;

				$("#" + tooltip_id).remove();

				var date = dateutil.obj_to_user(new Date(item.datapoint[0]));
				var tooltip_text = __("{0} on {1}", ["<strong>" + (item.datapoint[1] || 0) + "</strong>", date]);

				showTooltip(item.pageX, item.pageY, tooltip_text);
			}
		}
		else {
			$("#" + tooltip_id).remove();
			previousPoint = null;
		}
    });
}
