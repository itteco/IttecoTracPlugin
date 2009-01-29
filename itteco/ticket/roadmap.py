from trac.attachment import AttachmentModule
from trac.config import ListOption
from trac.core import Component
from trac.mimeview import Context
from trac.resource import Resource
from trac.ticket import TicketSystem
from trac.ticket.model import Type
from trac.ticket.roadmap import MilestoneModule, RoadmapModule, TicketGroupStats, DefaultTicketGroupStatsProvider, \
    apply_ticket_permissions,get_ticket_stats,milestone_stats_data
from trac.util.translation import _
from trac.web.chrome import add_link, add_stylesheet, add_warning
from itteco.ticket.model import StructuredMilestone
from itteco.init import IttecoEvnSetup

def get_tickets_for_milestones(env, db, milestone, fields='component', types=None):
    cursor = db.cursor()
    fields = isinstance(fields, list) or isinstance(fields, tuple)  and fields or [fields,]
    mils = isinstance(milestone, list) and milestone or [milestone,]
    place_holders = ("%s,"*len(mils))[:-1]

    types_sql_limitation = ''
    if types:
        types = isinstance(types, list) and types or [types,]
        types_sql_limitation = 'AND type in (%s)' % ("%s,"*len(types))[:-1]
        mils.extend(types)
        
    allowed_fields = TicketSystem(env).get_ticket_fields()
    field_and_type = [(f['name'], f.get('custom')) for f in allowed_fields if f['name'] in fields]
    
    sel_part = "SELECT id,status"
    from_part = " FROM ticket "
    order_part = None
    custom_fields = []
    for field, is_custom in field_and_type:
        if not is_custom:
            sel_part ="%s,%s" % (sel_part, field)
            if not order_part:
                order_part = "ORDER BY %s" % field
        else:
            custom_fields.append(field)
            cnt = len(custom_fields)
            sel_part ="%s,tc%d.value" % (sel_part, cnt)
            from_part = "%s LEFT OUTER JOIN ticket_custom tc%d ON (id=tc%d.ticket AND tc%d.name=%%s)" % (from_part,cnt, cnt, cnt)
            if not order_part:
                order_part = "ORDER BY tc%d.value" % cnt
                
    cursor.execute("%s %s WHERE milestone IN (%s) %s " % (sel_part, from_part, place_holders, types_sql_limitation), custom_fields+mils)
    tickets = []
    
    for fields in cursor:
        item = {'id': fields[0], 'status': fields[1]}
        for (field, is_custom), value in map(None, field_and_type, fields[2:]):
            item[field] = value
        tickets.append(item)
    return tickets

def get_tickets_for_structured_milestone(env, db, milestone, field='component', types=None):
    mils = []
    sub_mils = [milestone,]
    while sub_mils:
        mils.extend(sub_mils)
        cursor = db.cursor()
        cursor.execute("SELECT name FROM milestone_struct WHERE parent  IN (%s) " % ("%s,"*len(sub_mils))[:-1], sub_mils)
        sub_mils = [sub_milestone for sub_milestone, in cursor if sub_milestone not in mils]
    return get_tickets_for_milestones(env, db, mils, field, types)

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
            cursor.execute("SELECT status, sum(cast(tc.value as int)) FROM ticket t LEFT OUTER JOIN ticket_custom tc ON t.id=tc.ticket AND tc.name=%%s "
                           "WHERE id IN (%s) GROUP BY status" % ("%s,"*len(str_ids))[:-1], [field_name,]+str_ids)
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
                    group_cnt += cnt
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
            elif action == 'edit':
                return self._do_save(req, db, milestone)
            elif action == 'delete':
                self._do_delete(req, db, milestone)
        elif action in ('new', 'edit'):
            return self._render_editor(req, db, milestone)
        elif action == 'delete':
            return self._render_confirm(req, db, milestone)

        if not milestone.name:
            req.redirect(req.href.roadmap())

        return self._render_view(req, db, milestone)

    def _do_save(self, req, db, milestone):
        perm = milestone.exists and 'MILESTONE_MODIFY' or 'MILESTONE_CREATE'
        req.perm(milestone.resource).require(perm)

        old_name = milestone.name
        new_name = req.args.get('name')
        new_parent = req.args.get('parent')
        warnings = []
        def warn(msg):
            add_warning(req, msg)
            warnings.append(msg)
            
        if new_parent in (old_name, new_name):
            warn('Milestone "%s" cannot be parent for itself.,Please, give it another thought' % new_name)
        else:
            milestone.parent = new_parent
        MilestoneModule._do_save(self, req, db, milestone)
        if warnings:
            return self._render_editor(req, db, milestone)

    def _render_confirm(self, req, db, milestone):
        return self._delegate_call(req, db, milestone, MilestoneModule._render_confirm)

    def _render_editor(self, req, db, milestone):
        return self._delegate_call(req, db, milestone, MilestoneModule._render_editor)
        
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
        selected_type_names = [tkt_type.name for tkt_type in Type.select(self.env) if selected_types is None or tkt_type.value in selected_types]

        tickets = get_tickets_for_structured_milestone(self.env, db, milestone.name, (by, calc_on), selected_type_names)
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
        data.update(milestone_stats_data(req, stat, [m.name for m in IttecoRoadmapModule(self.env)._get_milestone_with_all_kids(milestone)]))

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
        tkt_types = [{'index':tkt.value, 'label': tkt.name, 'active': not selected_types or str(tkt.value) in selected_types} for tkt in Type.select(self.env)]        
        calculate_on = IttecoRoadmapModule(self.env).get_statistics_source(calc_on)
        data.update({'tkt_types': tkt_types,'calc_on': calculate_on})
        return 'itteco_milestone_view.html', data, None
        
class IttecoRoadmapModule(RoadmapModule):
    _calculate_statistics_on = ListOption('itteco-roadmap-config', 'calc_stats_on', [])
    def get_statistics_source(self, active = None):
        stats_source = [{'value' : None, 'label' : 'Number of tickets', 'active': not active},]
        fields = TicketSystem(self.env).get_ticket_fields()
        for field in fields:
            if field['name'] in self._calculate_statistics_on:
                stats_source.append({'value' : field['name'], 'label' : field['label'], 'active' : field['name']==active})
        return stats_source
        
    def process_request(self, req):
        milestone_realm = Resource('milestone')
        req.perm.require('MILESTONE_VIEW')

        showall = req.args.get('show') == 'all'
        db = self.env.get_db_cnx()
        milestones = [m for m in StructuredMilestone.select(self.env, showall, db)
                      if 'MILESTONE_VIEW' in req.perm(m.resource)]
                      
        if req.args.get('format') == 'ics':
            self.render_ics(req, db, milestones)
            return
        level = int(req.args.get('mil_type', '2'))
        i =0
        calc_on = req.args.get('calc_on', None)
        while i<level:
            next_level_mils = []
            for m in milestones:
                next_level_mils.extend(m.kids)
            milestones = next_level_mils
            i+=1
            
        selected_types = req.args.get('tkt_type', None)
        if selected_types:
            selected_types = isinstance(selected_types, list) and selected_types or [selected_types,]
        selected_type_names = [tkt_type.name for tkt_type in Type.select(self.env) if selected_types is None or tkt_type.value in selected_types]

        stats = []
        for milestone in milestones:
            tickets = get_tickets_for_structured_milestone(self.env, db, milestone.name, calc_on, selected_type_names)
            tickets = apply_ticket_permissions(self.env, req, tickets)
            stat = SelectionTicketGroupStatsProvider(self.env).get_ticket_group_stats(tickets, calc_on)
            stats.append(milestone_stats_data(req, stat, [m.name for m in self._get_milestone_with_all_kids(milestone)]))

        # FIXME should use the 'webcal:' scheme, probably
        username = None
        if req.authname and req.authname != 'anonymous':
            username = req.authname
        icshref = req.href.roadmap(show=req.args.get('show'), user=username,
                                   format='ics')
        add_link(req, 'alternate', icshref, _('iCalendar'), 'text/calendar',
                 'ics')
        visibility = [{'index':idx, 'label': label, 'active': idx==level} for idx, label in enumerate(IttecoEvnSetup(self.env).milestone_levels)]
        tkt_types = [{'index':tkt.value, 'label': tkt.name, 'active': not selected_types or str(tkt.value) in selected_types} for tkt in Type.select(self.env)]
        
        calculate_on = self.get_statistics_source(req.args.get('calc_on', None))
        data = {
            'milestones': milestones,
            'milestone_stats': stats,
            'mil_types': visibility,
            'tkt_types': tkt_types,
            'calc_on': calculate_on,
            'queries': [],
            'showall': showall,
        }
        return 'itteco_roadmap.html', data, None
        
    def _get_milestone_with_all_kids(self, milestone):
        res = []
        sub_mils = [milestone,]
        while sub_mils:
            res.extend(sub_mils)
            next_level_mils = []
            for m in sub_mils:
                next_level_mils.extend(m.kids)
            sub_mils = next_level_mils
        return res