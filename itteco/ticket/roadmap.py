from datetime import date, datetime

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.attachment import AttachmentModule
from trac.config import ListOption, Option, ExtensionOption
from trac.core import implements, Component
from trac.mimeview import Context
from trac.resource import Resource
from trac.ticket import TicketSystem

from trac.ticket.model import Type
from trac.ticket.roadmap import MilestoneModule, RoadmapModule, TicketGroupStats, \
    DefaultTicketGroupStatsProvider, apply_ticket_permissions,get_ticket_stats,milestone_stats_data
from trac.util.datefmt import get_date_format_hint, \
    parse_date, utc, format_datetime, to_datetime, localtz, to_timestamp
from trac.util.translation import _

from trac.web.api import ITemplateStreamFilter
from trac.web.chrome import Chrome, add_link, add_stylesheet, add_warning
from trac.wiki.formatter import format_to

from itteco.init import IttecoEvnSetup
from itteco.utils.render import add_jscript
from itteco.scrum.burndown import IBurndownInfoProvider
from itteco.ticket.api import MilestoneSystem
from itteco.ticket.model import StructuredMilestone
from itteco.ticket.report import IttecoReportModule
from itteco.ticket.utils import get_fields_by_names, get_tickets_for_milestones
from itteco.utils import json

def get_tickets_for_structured_milestone(env, db, milestone, field='component', types=None):
    field = ['milestone'] + ( field and (isinstance(field, basestring) and [field,] or field) or [])
    mils = []
    sub_mils = [milestone,]
    while sub_mils:
        mils.extend(sub_mils)
        cursor = db.cursor()
        cursor.execute("SELECT milestone"
                        " FROM milestone_custom"
                       " WHERE name='parent'"
                         " AND value IN (%s) " % ("%s,"*len(sub_mils))[:-1], sub_mils)
        sub_mils = [sub_milestone for sub_milestone, in cursor if sub_milestone not in mils]
    return get_tickets_for_milestones(db, mils, get_fields_by_names(env, field), types)

class SelectionTicketGroupStatsProvider(Component):
    def get_ticket_group_stats(self, tickets, field_name=None):
        total_cnt = 0
        ticket_ids= []
        for ticket in tickets:
            try:
                ticket_ids.append(ticket['id'])
                total_cnt += int(ticket.get(field_name, 0))
            except:
                pass

        if not field_name:
            return DefaultTicketGroupStatsProvider(self.env).get_ticket_group_stats(ticket_ids)

        all_statuses = set(TicketSystem(self.env).get_all_status())
        status_cnt = {}
        for s in all_statuses:
            status_cnt[s] = 0
        if total_cnt:
            cursor = self.env.get_db_cnx().cursor()
            str_ids = [str(x) for x in sorted(ticket_ids)]
            cursor.execute("SELECT status, sum(cast('0'||tc.value as int))"+\
                " FROM ticket t LEFT OUTER JOIN ticket_custom tc ON t.id=tc.ticket AND tc.name=%s "+\
                " WHERE id IN (%s) GROUP BY status" % ("%s,"*len(str_ids))[:-1], [field_name,]+str_ids)
            for s, cnt in cursor:
                status_cnt[s] = cnt

        stat = TicketGroupStats('ticket status', 'ticket')
        remaining_statuses = set(all_statuses)
        groups =  DefaultTicketGroupStatsProvider(self.env)._get_ticket_groups()
        catch_all_group = None
        # we need to go through the groups twice, so that the catch up group
        # doesn't need to be the last one in the sequence
        for group in groups:
            status_str = group['status'].strip()
            if status_str == '*':
                if catch_all_group:
                    raise TracError(_(
                        "'%(group1)s' and '%(group2)s' milestone groups "
                        "both are declared to be \"catch-all\" groups. "
                        "Please check your configuration.",
                        group1=group['name'], group2=catch_all_group['name']))
                catch_all_group = group
            else:
                group_statuses = set([s.strip()
                                      for s in status_str.split(',')]) \
                                      & all_statuses
                if group_statuses - remaining_statuses:
                    raise TracError(_(
                        "'%(groupname)s' milestone group reused status "
                        "'%(status)s' already taken by other groups. "
                        "Please check your configuration.",
                        groupname=group['name'],
                        status=', '.join(group_statuses - remaining_statuses)))
                else:
                    remaining_statuses -= group_statuses
                group['statuses'] = group_statuses
        if catch_all_group:
            catch_all_group['statuses'] = remaining_statuses
        for group in groups:
            group_cnt = 0
            query_args = {}
            for s, cnt in status_cnt.iteritems():
                if s in group['statuses']:
                    group_cnt += cnt or 0
                    query_args.setdefault('status', []).append(s)
            for arg in [kv for kv in group.get('query_args', '').split(',')
                        if '=' in kv]:
                k, v = [a.strip() for a in arg.split('=', 1)]
                query_args[k] = v
            stat.add_interval(group.get('label', group['name']), 
                              group_cnt, query_args,
                              group.get('css_class', group['name']),
                              bool(group.get('overall_completion')))
        stat.refresh_calcs()
        return stat


class IttecoMilestoneModule(MilestoneModule):

    # IRequestHandler methods
    def process_request(self, req):
        milestone_id = req.args.get('id')
        req.perm('milestone', milestone_id).require('MILESTONE_VIEW')
        
        add_link(req, 'up', req.href.roadmap(), _('Roadmap'))

        db = self.env.get_db_cnx()
        milestone = StructuredMilestone(self.env, milestone_id, db)
        action = req.args.get('action', 'view')

        if req.method == 'POST':
            if req.args.has_key('cancel'):
                if milestone.exists:
                    req.redirect(req.href.milestone(milestone.name))
                else:
                    req.redirect(req.href.roadmap())
            elif action == 'delete':
                self._do_delete(req, db, milestone)
            elif action == 'edit':
                return self._do_save(req, db, milestone)
        elif action in ('new', 'edit'):
            return self._render_editor(req, db, milestone)
        elif action == 'delete':
            return self._render_confirm(req, db, milestone)
        elif action == 'start':
            return self._do_start(req, db, milestone)

        if not milestone.name:
            req.redirect(req.href.roadmap())

        return self._render_view(req, db, milestone)

    def _do_save(self, req, db, milestone):
        perm = milestone.exists and 'MILESTONE_MODIFY' or 'MILESTONE_CREATE'
        req.perm(milestone.resource).require(perm)

        self._populate_custom_fields(req, milestone)
        action = req.args.get('workflow_action')
        actions = MilestoneSystem(self.env).get_available_actions(
            req, milestone)
            
        if action not in actions:
            raise TracError(_('Invalid action "%(name)s"', name=action))
            # (this should never happen in normal situations)
        field_changes, problems = self.get_milestone_changes(req, milestone, action)
        if problems:
            for problem in problems:
                add_warning(req, problem)
                add_warning(req,
                            tag(tag.p('Please review your configuration, '
                                      'probably starting with'),
                                tag.pre('[trac]\nworkflow = ...\n'),
                                tag.p('in your ', tag.tt('trac.ini'), '.'))
                            )
        for key in field_changes:
            milestone[key] = field_changes[key]['new']

        old_name = milestone.name
        new_name = req.args.get('name')
        new_parent_name = req.args.get('parent')
        warnings = []
        def warn(msg):
            add_warning(req, msg)
            warnings.append(msg)
            
        if new_parent_name in (old_name, new_name):
            warn('Milestone "%s" cannot be parent for itself.,Please, give it another thought' % new_name)
        else:
            milestone['parent'] = new_parent_name
            
        started = req.args.get('starteddate', '')
        if 'started' in req.args:
            started = started and parse_date(started, req.tz) or None
            if started and started > datetime.now(utc):
                warn(_('Started date may not be in the future'))
        else:
            started = None
        milestone.started = started

        if warnings:
            return self._render_editor(req, db, milestone)
        else:
            results = MilestoneModule._do_save(self, req, db, milestone)
            return  results
            
    def get_milestone_changes(self, req, milestone, selected_action):
        """Returns a dictionary of field changes.
        
        The field changes are represented as:
        `{field: {'old': oldvalue, 'new': newvalue, 'by': what}, ...}`
        """
        # Start with user changes
        field_changes = {}
        for field, value in milestone._old.iteritems():
            field_changes[field] = {'old': value,
                                    'new': milestone[field],
                                    'by':'user'}
        # Apply controller changes corresponding to the selected action
        problems = []
        for controller in self._get_action_controllers(req, milestone,
                                                       selected_action):
            cname = controller.__class__.__name__
            action_changes = controller.get_milestone_changes(req, milestone,
                                                           selected_action)
            for key in action_changes.keys():
                old = milestone[key]
                new = action_changes[key]
                # Check for conflicting changes between controllers
                if key in field_changes:
                    last_new = field_changes[key]['new']
                    last_by = field_changes[key]['by'] 
                    if last_new != new and last_by:
                        problems.append('%s changed "%s" to "%s", '
                                        'but %s changed it to "%s".' %
                                        (cname, key, new, last_by, last_new))
                field_changes[key] = {'old': old, 'new': new, 'by': cname}
        # Detect non-changes
        for key, item in field_changes.items():
            if item['old'] == item['new']:
                del field_changes[key]
        return field_changes, problems

    def _render_confirm(self, req, db, milestone):
        return self._delegate_call(req, db, milestone, MilestoneModule._render_confirm)

    def _render_editor(self, req, db, milestone):
        template, data, content_type = self._delegate_call(req, db, milestone, MilestoneModule._render_editor)
        selected_action = req.args.get('workflow_action')
        
        action_controls = []
        sorted_actions = MilestoneSystem(self.env).get_available_actions(req,
                                                                      milestone)
        for action in sorted_actions:
            first_label = None
            hints = []
            widgets = []
            for controller in self._get_action_controllers(req, milestone,
                                                           action):
                label, widget, hint = controller.render_milestone_action_control(
                    req, milestone, action)
                if not first_label:
                    first_label = label
                widgets.append(widget)
                hints.append(hint)
            action_controls.append((action, first_label, tag(widgets), hints))
        if not selected_action:
            selected_action = action_controls[0][0]
        data.update(
            {
                'workflow_action': selected_action,
                'action_controls' : action_controls,
                'structured_milestones' : data['milestones']
            }
        )
        return 'itteco_milestone_edit.html', data, content_type
        
    def _delegate_call(self, req, db, milestone, func):
        template, data, content_type = func(self, req, db, milestone)
        if data:
            data['milestones'] = StructuredMilestone.select(self.env, False, db)
        return template, data, content_type
        
    def _render_view(self, req, db, milestone):
        milestone_groups = []
        available_groups = []
        component_group_available = False
        ticket_fields = TicketSystem(self.env).get_ticket_fields()
        calc_on = req.args.get('calc_on', None)
        
        # collect fields that can be used for grouping
        for field in ticket_fields:
            if field['type'] == 'select' and field['name'] != 'milestone' \
                    or field['name'] in ('owner', 'reporter'):
                available_groups.append({'name': field['name'],
                                         'label': field['label']})
                if field['name'] == 'component':
                    component_group_available = True

        # determine the field currently used for grouping
        by = None
        if component_group_available:
            by = 'component'
        elif available_groups:
            by = available_groups[0]['name']
        by = req.args.get('by', by)

        selected_types = req.args.get('tkt_type', None)
        if selected_types:
            selected_types = isinstance(selected_types, list) and selected_types or [selected_types,]
        selected_type_names = [tkt_type.name for tkt_type in Type.select(self.env) 
            if selected_types is None or tkt_type.value in selected_types]

        tickets = get_tickets_for_structured_milestone(
            self.env, db, milestone.name, [by, calc_on], selected_type_names)
        tickets = apply_ticket_permissions(self.env, req, tickets)
        stat = SelectionTicketGroupStatsProvider(self.env).get_ticket_group_stats(tickets, calc_on)
        self.env.log.debug("The collected stats '%s'" % stat)
        context = Context.from_request(req, milestone.resource)
        data = {
            'context': context,
            'milestone': milestone,
            'attachments': AttachmentModule(self.env).attachment_data(context),
            'available_groups': available_groups, 
            'grouped_by': by,
            'groups': milestone_groups
            }
        data.update(
            milestone_stats_data(
                req, stat, \
                [m.name for m in _get_milestone_with_all_kids(milestone)]))

        if by:
            groups = []
            for field in ticket_fields:
                if field['name'] == by:
                    if field.has_key('options'):
                        groups = field['options']
                    else:
                        cursor = db.cursor()
                        cursor.execute("SELECT DISTINCT %s FROM ticket "
                                       "ORDER BY %s" % (by, by))
                        groups = [row[0] for row in cursor]

            max_count = 0
            group_stats = []

            for group in groups:
                group_tickets = [t for t in tickets if t[by] == group]
                if not group_tickets:
                    continue

                gstat = get_ticket_stats(self.stats_provider, group_tickets)
                if gstat.count > max_count:
                    max_count = gstat.count

                group_stats.append(gstat) 

                gs_dict = {'name': group}
                gs_dict.update(milestone_stats_data(req, gstat, milestone.name,
                                                    by, group))
                milestone_groups.append(gs_dict)

            for idx, gstat in enumerate(group_stats):
                gs_dict = milestone_groups[idx]
                percent = 1.0
                if max_count:
                    percent = float(gstat.count) / float(max_count) * 100
                gs_dict['percent_of_max_total'] = percent
        tkt_types = [{'index':tkt.value, 'label': tkt.name, 
            'active': not selected_types or str(tkt.value) in selected_types} 
            for tkt in Type.select(self.env)]        
        calculate_on = IttecoRoadmapModule(self.env).get_statistics_source(calc_on)
        
        data.update(
            {
                'tkt_types': tkt_types,
                'calc_on': calculate_on,
            }
        )
        
        self._add_tickets_report_data(milestone, req, data)
        
        return 'itteco_milestone_view.html', data, None
        
    def _add_tickets_report_data(self, milestone, req, data):
        tickets_report = MilestoneSystem(self.env).tickets_report
        if tickets_report:
            req.args['MILESTONE'] = milestone.name
            req.args['id']=tickets_report
            report_data = IttecoReportModule(self.env).get_report_data(req, tickets_report)
            self.env.log.debug('report_data="%s"' % (report_data,))
            data.update(report_data)
            
            add_jscript(req, 'stuff/plugins/jquery.rpc.js')
            add_jscript(req, 'stuff/ui/plugins/jquery.jeditable.js')
            add_jscript(req, 'editable_report.js')
            add_stylesheet(req, 'itteco/css/report.css')
            data['fields_config'] = IttecoReportModule(self.env).fields_dict(data.get('header_groups',[]))
        data['render_report'] = tickets_report or None
            

    # ITimelineEventProvider methods
    def get_timeline_events(self, req, start, stop, filters):
        if 'milestone' in filters:
            milestone_realm = Resource('milestone')
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            # TODO: creation and (later) modifications should also be reported
            cursor.execute("SELECT %s, m.name, m.description"
                            " FROM milestone m,"
                                 " milestone_custom mc"
                           " WHERE m.name = mc.milestone"
                             " AND mc.name='started'"
                             " AND %s>=%%s AND %s<=%%s " % (db.cast('mc.value', 'int')),
                           (to_timestamp(start), to_timestamp(stop)))
            for started, name, description in cursor:
                milestone = milestone_realm(id=name)
                if 'MILESTONE_VIEW' in req.perm(milestone):
                    yield('milestone', datetime.fromtimestamp(started, utc),
                          '', (milestone, description, True)) 

            for event in MilestoneModule.get_timeline_events(self, req, start, stop, filters):
                yield event

    def render_timeline_event(self, context, field, event):
        started = False
        if len(event[3])==3:
            milestone, description, started = event[3]
        else:
            milestone, description = event[3]
            
        if field == 'url':
            return context.href.milestone(milestone.id)
        elif field == 'title':
            return tag('Milestone ', tag.em(milestone.id), started and ' started' or ' completed')
        elif field == 'description':
            return format_to(self.env, None, context(resource=milestone),
                             description)
                             
    def _get_action_controllers(self, req, milestone, action):
        """Generator yielding the controllers handling the given `action`"""
        for controller in MilestoneSystem(self.env).action_controllers:
            actions = [a for w,a in
                       controller.get_milestone_actions(req, milestone)]
            if action in actions:
                yield controller
                
    def _populate_custom_fields(self, req, milestone):
        fields = req.args
        for k,v in fields.items():
            if k.startswith('field_'):
                milestone[k[6:]] = v
            
class IttecoRoadmapModule(RoadmapModule):
    _calculate_statistics_on = ListOption('itteco-roadmap-config', 'calc_stats_on', [])   
    def get_statistics_source(self, active = None):
        stats_source = [
            {
                'value' : None, 
                'label' : _('Number of tickets'), 
                'active': not active
            }
        ]
        fields = TicketSystem(self.env).get_ticket_fields()
        for field in fields:
            if field['name'] in self._calculate_statistics_on:
                stats_source.append({'value' : field['name'], 'label' : field['label'], 
                    'active' : field['name']==active})
        return stats_source
        
    def process_request(self, req):
        milestone_realm = Resource('milestone')
        req.perm.require('MILESTONE_VIEW')

        showall = req.args.get('show') == 'all'
        db = self.env.get_db_cnx()
        milestones = [m for m in StructuredMilestone.select(self.env, True, db)
                        if 'MILESTONE_VIEW' in req.perm(m.resource)]
        requested_fmt = req.args.get('format')
        if requested_fmt == 'ics':
            self.render_ics(req, db, milestones)
            return
        max_level = len(IttecoEvnSetup(self.env).milestone_levels)
        max_level = max_level and max_level-1 or 0;
        current_level = int(req.args.get('mil_type', max_level))
        
        if current_level==-1:
            #show all milestones regardless to the level
            milestones = sum([_get_milestone_with_all_kids(mil) for mil in milestones], [])
        else:
            #filter by level
            i =0        
            while i<current_level:
                next_level_mils = []
                for m in milestones:
                    next_level_mils.extend(m.kids)
                milestones = next_level_mils
                i+=1

        calc_on = req.args.get('calc_on')
        selected_types = req.args.get('tkt_type')
        if selected_types:
            selected_types = isinstance(selected_types, list) and selected_types or [selected_types,]
        selected_type_names = [tkt_type.name for tkt_type in Type.select(self.env) 
            if selected_types is None or tkt_type.value in selected_types]

        stats = []
        milestones = [mil for mil in milestones if showall or not mil.is_completed]
        for milestone in milestones:
            tickets = get_tickets_for_structured_milestone(
                self.env, db, milestone.name, calc_on, selected_type_names)
            tickets = apply_ticket_permissions(self.env, req, tickets)
            stat = SelectionTicketGroupStatsProvider(self.env).get_ticket_group_stats(tickets, calc_on)
            stats.append(
                milestone_stats_data(
                    req, stat, [m.name for m in _get_milestone_with_all_kids(milestone)]))

        if requested_fmt=='json':
            self._render_milestones_stats_as_json(req, milestones, stats)
            return
        # FIXME should use the 'webcal:' scheme, probably
        username = None
        if req.authname and req.authname != 'anonymous':
            username = req.authname
        icshref = req.href.roadmap(show=req.args.get('show'), user=username,
                                   format='ics')
        add_link(req, 'alternate', icshref, _('iCalendar'), 'text/calendar',
                 'ics')
        visibility = [{'index':idx, 'label': label, 'active': idx==current_level} 
            for idx, label in enumerate(IttecoEvnSetup(self.env).milestone_levels)]
        tkt_types = [{'index':tkt.value, 'label': tkt.name, 
            'active': not selected_types or str(tkt.value) in selected_types} 
                for tkt in Type.select(self.env)]
        
        calculate_on = self.get_statistics_source(req.args.get('calc_on'))
        data = {
            'milestones': milestones,
            'milestone_stats': stats,
            'mil_types': visibility,
            'tkt_types': tkt_types,
            'calc_on': calculate_on,
            'queries': [],
            'showall': showall,
        }
        self.env.log.debug('data:%s' % data)
        return 'itteco_roadmap.html', data, None
                        
    def _render_milestones_stats_as_json(self, req, milestones, statistics):        
        stats = []
        for idx, milestone in enumerate(milestones):
            stat = statistics[idx]['stats']
            stats.append(
                {'stats': 
                    {
                        'count': stat.count, 
                        'done_count':stat.done_count, 
                        'done_percent':stat.done_percent
                    },
                    'milestone': milestone.name,
                    'level': milestone.level,
                    'due': format_datetime(milestone.due,'%Y-%m-%d %H:%M:%S')
                }
            )
        json_response = json.write(stats)
        if 'jsoncallback' in req.args:
            json_response = req.args['jsoncallback']+'('+json_response+')'
        req.send(json_response, 'application/x-javascript')
        
def _get_milestone_with_all_kids(milestone):
    res = []
    sub_mils = [milestone,]
    while sub_mils:
        res.extend(sub_mils)
        next_level_mils = []
        for m in sub_mils:
            next_level_mils.extend(m.kids)
        sub_mils = next_level_mils
    return res