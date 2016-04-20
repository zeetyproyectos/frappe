from __future__ import unicode_literals
import json, base64, os
import frappe.utils
from frappe.celery_app import get_celery
from frappe.utils.file_lock import check_lock, LockTimeoutError
from frappe.utils.scheduler import is_scheduler_disabled
from collections import Counter
from operator import itemgetter

def get_redis_conn():
	"Returns the redis connection that celery would use"
	app = get_celery()
	with app.connection() as conn:
		r = conn.default_channel.client
	return r

def get_queues(site=None):
	"Returns the name of queues where frappe enqueues tasks as per the configuration"
	queues = ["celery"]
	sites = [site] if site else frappe.utils.get_sites()
	for site in sites:
		queues.append(site)
		queues.append('longjobs@' + site)

	return queues

def get_task_body(taskstr):
	return json.loads(base64.decodestring(json.loads(taskstr)['body']))

def purge_pending_tasks(event=None, site=None):
	"""
	Purge tasks of the event event type. Passing 'all' will not purge all
	events but of the all event type, ie. the ones that are enqueued every five
	mintues and would any leave daily, hourly and weekly tasks
	"""
	r = get_redis_conn()

	event_tasks = []
	for app in frappe.get_all_apps(True):
		all_events = frappe.get_hooks(app_name=app).get('scheduler_events', {})
		if event:
			event_tasks += all_events.get(event) or []
		else:
			# tasks of all events
			for tasks in all_events.values():
				event_tasks += tasks or []

	count = 0

	for queue in get_queues():
		for taskstr in r.lrange(queue, 0, -1):
			taskbody = get_task_body(taskstr)
			kwargs = taskbody.get('kwargs')
			if kwargs:
				if site and kwargs.get('site') != site:
					continue

				if event:
					if kwargs.get('handler') and kwargs.get('handler') in event_tasks:
						r.lrem(queue, taskstr)
						count += 1
				else:
					r.lrem(queue, taskstr)
					count += 1
	return count

def get_pending_task_count():
	"Get count of pending tasks"
	r = get_redis_conn()
	pending = 0
	for queue in get_queues():
		pending += r.llen(queue)
	return pending

def get_timedout_locks():
	"Get list of stale locks from all sites"
	old_locks=[]
	for site in frappe.utils.get_sites():
		locksdir = os.path.join(site, 'locks')
		for lock in os.listdir(locksdir):
			lock_path = os.path.join(locksdir, lock)
			try:
				check_lock(lock_path)
			except LockTimeoutError:
				old_locks.append(lock_path)
	return old_locks

def check_if_workers_online():
	app = get_celery()
	if app.control.inspect().ping():
		return True
	return False

def dump_queue_status(site=None):
	"""
	Dumps pending events and tasks per queue
	"""
	ret = []
	r = get_redis_conn()
	for queue in get_queues(site=site):
		if r.llen(queue):
			queue_details = {
				'queue': queue,
				'len': r.llen(queue),
			}
			queue_details.update(get_task_count_for_queue(queue))
			ret.append(queue_details)

	ret = sorted(ret, key=itemgetter('len'), reverse=True)
	ret.insert(0, {
		'total': get_pending_task_count()
	})
	return ret

def get_task_count_for_queue(queue):
	"""
	For a given queue, returns the count of every pending task and aggregate of
	events pending
	"""
	r = get_redis_conn()
	tasks = [get_task_body(taskstr) for taskstr in r.lrange(queue, 0, -1)]
	task_names = [task['task'] for task in tasks]
	task_counts = Counter(task_names)
	event_counts = Counter(task['kwargs'].get('event') for task in tasks)
	return {
		'task_counts': task_counts,
		'event_counts': event_counts
	}

def get_running_tasks():
	ret = {}
	app = get_celery()
	inspect = app.control.inspect()
	active = inspect.active()
	if not active:
		return []
	for worker in active:
		ret[worker] = []
		for task in active[worker]:
			ret[worker].append({
				'id': task['id'],
				'name': task['name'],
				'routing_key': task['delivery_info']['routing_key'],
				'args': task['args'],
				'kwargs': task['kwargs']
			})
	return ret


def doctor():
	"""
	Prints diagnostic information for the scheduler
	"""
	print "Inspecting workers and queues..."
	workers_online = check_if_workers_online()
	pending_tasks = get_pending_task_count()

	print "Finding locks..."
	locks = get_timedout_locks()

	print "Checking scheduler status..."
	for site in frappe.utils.get_sites():
		frappe.init(site)
		frappe.connect()
		if is_scheduler_disabled():
			print "{0:40}: Scheduler disabled via System Settings or site_config.json".format(site)
		frappe.destroy()

	print "Workers online:", workers_online
	print "Pending tasks", pending_tasks
	print "Timed out locks:"
	print "\n".join(locks)
	if (not workers_online) or (pending_tasks > 4000) or locks:
		return 1

	print "Note: To view pending tasks, use bench dump-queue-status"

	return True

def celery_doctor(site=None):
	queues = dump_queue_status(site=site)
	running_tasks = get_running_tasks()
	print 'Queue Status'
	print '------------'
	print json.dumps(queues, indent=1)
	print ''
	print 'Running Tasks'
	print '------------'
	print json.dumps(running_tasks, indent=1)

def inspect_queue():
	print 'Pending Tasks Queue'
	print '-'*20
	r = get_redis_conn()
	for queue in get_queues():
		for taskstr in r.lrange(queue, 0, -1):
			taskbody = get_task_body(taskstr)
			kwargs = taskbody.get('kwargs')
			if kwargs:
				print frappe.as_json(kwargs)
