from datetime import date, datetime, time
import re

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.attachment import AttachmentModule
from trac.config import ListOption, Option, ExtensionOption
from trac.core import implements, Component, TracError
from trac.mimeview import Context
from trac.perm import IPermissionRequestor
from trac.resource import Resource, ResourceNotFound, IResourceManager, get_resource_url, get_resource_name
from trac.search import ISearchSource, search_to_sql, shorten_result

from trac.ticket import TicketSystem, group_milestones
from trac.ticket.api import ITicketChangeListener
from trac.ticket.model import Type, Milestone
from trac.ticket.roadmap import MilestoneModule, RoadmapModule, TicketGroupStats, \
    ITicketGroupStatsProvider, DefaultTicketGroupStatsProvider, \
    apply_ticket_permissions,get_ticket_stats,milestone_stats_data
    
from trac.ticket.web_ui import TicketModule
from trac.timeline.api import ITimelineEventProvider

from trac.util import get_reporter_id
from trac.util.datefmt import get_date_format_hint, \
    parse_date, utc, format_datetime, to_datetime, localtz, to_timestamp, \
    get_datetime_format_hint
from trac.util.translation import _

from trac.web import IRequestHandler
from trac.web.api import ITemplateStreamFilter
from trac.web.chrome import Chrome, add_link, add_notice, add_stylesheet, \
    add_warning, INavigationContributor

from trac.wiki.api import IWikiSyntaxProvider
from trac.wiki.formatter import format_to

from tracrpc.api import IXMLRPCHandler

from itteco.init import IttecoEvnSetup
from itteco.utils.render import add_jscript
from itteco.scrum.burndown import IBurndownInfoProvider
from itteco.ticket.api import MilestoneSystem
from itteco.ticket.model import StructuredMilestone, milestone_ticket_type
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
        cursor.execute("SELECT m.name"
                        " FROM milestone m,"
                             " ticket t"
                       " WHERE m.name=t.summary"
                         " AND t.type=%%s"
                         " AND t.milestone IN (%s)" % ("%s,"*len(sub_mils))[:-1],
                        tuple([milestone_ticket_type]+sub_mils))
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

class IttecoMilestoneModule(Component):

    implements(INavigationContributor, IPermissionRequestor, IRequestHandler,
               ITimelineEventProvider, IWikiSyntaxProvider, IResourceManager,
               ISearchSource, ITicketChangeListener, IXMLRPCHandler)
               
    stats_provider = ExtensionOption('milestone', 'stats_provider',
                                     ITicketGroupStatsProvider,
                                     'DefaultTicketGroupStatsProvider',
        """Name of the component implementing `ITicketGroupStatsProvider`, 
        which is used to collect statistics on groups of tickets for display
        in the milestone views.""")

    date_fields = ('started', 'duedate', 'completed')

    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'roadmap'

    def get_navigation_items(self, req):
        return []

    # IPermissionRequestor methods

    def get_permission_actions(self):
        actions = ['MILESTONE_CREATE', 'MILESTONE_DELETE', 'MILESTONE_MODIFY',
                   'MILESTONE_VIEW']
        return actions + [('MILESTONE_ADMIN', actions)]

    # ITimelineEventProvider methods

    def get_timeline_filters(self, req):
        if 'MILESTONE_VIEW' in req.perm:
            yield ('milestone', _('Milestones'))

    def get_timeline_events(self, req, start, stop, filters):
        if 'milestone' in filters:
            self.env.log.debug('get_timeline_events')
            milestone_realm = Resource('milestone')
            ts_start = to_timestamp(start)
            ts_stop = to_timestamp(stop)
            
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            
            status_map = {'new': ('newmilestone', 'created'),
                          'reopened': ('reopenedmilestone', 'reopened'),
                          'closed': ('closedmilestone', 'closed'),
                          'edit': ('editedmilestone', 'updated'),
                          'comment': ('editedmilestone', 'commented')}
                          
            def produce_event((id, ts, author, type, summary, description),
                              status, comment):
                milestone = milestone_realm(id=summary)
                if 'MILESTONE_VIEW' not in req.perm(milestone):
                    return None
                kind, verb = status_map[status]
                return (kind, datetime.fromtimestamp(ts, utc), author,
                        (milestone, verb, status, description, comment), self)

            cursor.execute("SELECT id, time, reporter, type, summary, "
                           "       description "
                           "  FROM ticket "
                           " WHERE type='$milestone$' AND time>=%s AND time<=%s",
                           (ts_start, ts_stop))
            for row in cursor:
                ev = produce_event(row, 'new', None)
                if ev:
                    yield ev

            # TODO: creation and (later) modifications should also be reported
            cursor.execute("SELECT t.id,tc.time,tc.author,t.type,t.summary, "
                           "       tc.newvalue "
                           "  FROM ticket_change tc "
                           "    INNER JOIN ticket t ON t.id = tc.ticket "
                           "      AND t.type='$milestone$' "
                           "      AND tc.time>=%s AND tc.time<=%s "
                           "      AND tc.field='comment' "
                           "      AND tc.newvalue IS NOT NULL "
                           "      AND tc.newvalue<>'' "
                           "ORDER BY tc.time"
                           % (ts_start, ts_stop))

            for row in cursor:
                ev = produce_event(row, 'comment', row[-1])
                if ev:
                    yield ev
            cursor.execute("SELECT id, m.completed,t.reporter,t.type,t.summary, "
                           "       t.description "
                           "  FROM milestone m "
                           "    INNER JOIN ticket t ON t.type='$milestone$' AND t.summary=m.name "
                           "WHERE completed>=%s AND completed<=%s",
                           (to_timestamp(start), to_timestamp(stop)))
            
            for row in cursor:
                ev = produce_event(row, 'closed', row[-1])
                if ev:
                    yield ev

            # Attachments
            for event in AttachmentModule(self.env).get_timeline_events(
                req, milestone_realm, start, stop):
                yield event

    def render_timeline_event(self, context, field, event):
        milestone, verb, status, description, comment = event[3]
        if field == 'url':
            return context.href.milestone(milestone.id)
        elif field == 'title':
            return tag('Milestone ', tag.em(milestone.id), ' ', verb)
        elif field == 'description':
            return format_to(self.env, None, context(resource=milestone),
                             status=='comment' and comment or description)

    # IRequestHandler methods

    def match_request(self, req):
        match = re.match(r'/milestone(?:/(.+))?$', req.path_info)
        if match:
            if match.group(1):
                req.args['id'] = match.group(1)
            return True

    def process_request(self, req):
        milestone_id = req.args.get('id')
        req.perm('milestone', milestone_id).require('MILESTONE_VIEW')
        
        add_link(req, 'up', req.href.roadmap(), _('Roadmap'))

        db = self.env.get_db_cnx() # TODO: db can be removed
        milestone = StructuredMilestone(self.env, milestone_id, db)
        action = req.args.get('action', 'view')

        if req.method == 'POST':
            if req.args.has_key('cancel'):
                req.redirect(req.href.roadmap())
            elif action == 'delete':
                self._do_delete(req, db, milestone)
            return self._do_save(req, db, milestone)

        elif action in ('new', 'edit', 'view'):
            return self._render_editor(req, db, milestone)
        elif action == 'delete':
            return self._render_confirm(req, db, milestone)

        req.redirect(req.href.roadmap())

    # Internal methods

    def _do_delete(self, req, db, milestone):
        req.perm(milestone.resource).require('MILESTONE_DELETE')

        retarget_to = None
        if req.args.has_key('retarget'):
            retarget_to = req.args.get('target') or None
        milestone.delete(retarget_to, req.authname)
        db.commit()
        add_notice(req, _('The milestone "%(name)s" has been deleted.',
                          name=milestone.name))
        req.redirect(req.href.roadmap())

    def _do_save(self, req, db, milestone):
        if milestone.exists:
            req.perm(milestone.resource).require('MILESTONE_MODIFY')
        else:
            req.perm(milestone.resource).require('MILESTONE_CREATE')
        
        ticket_module = TicketModule(self.env)
        ticket_module._populate(req, milestone.ticket, False)
        if not milestone.exists:
            reporter_id = get_reporter_id(req, 'author')
            milestone.ticket.values['reporter'] = reporter_id

        action = req.args.get('action', 'leave')

        field_changes, problems = ticket_module.get_ticket_changes(req, milestone.ticket,
                                    action)
        if problems:
            for problem in problems:
                add_warning(req, problem)
                add_warning(req,
                            tag(tag.p('Please review your configuration, '
                                      'probably starting with'),
                                tag.pre('[trac]\nworkflow = ...\n'),
                                tag.p('in your ', tag.tt('trac.ini'), '.'))
                            )

        ticket_module._apply_ticket_changes(milestone.ticket, field_changes)

        old_name = milestone.name
        new_name = milestone.ticket['summary']
        
        milestone.name = new_name
        milestone.description = milestone.ticket['description']

        due = req.args.get('duedate', '')
        milestone.due = due and parse_date(due, tzinfo=req.tz) or None
        milestone.ticket['duedate']=milestone.due and str(to_timestamp(milestone.due)) or None

        completed = req.args.get('completeddate', '')
        retarget_to = req.args.get('target')

        # Instead of raising one single error, check all the constraints and
        # let the user fix them by going back to edit mode showing the warnings
        warnings = []
        def warn(msg):
            add_warning(req, msg)
            warnings.append(msg)

        # -- check the name
        if new_name:
            if new_name != old_name:
                # check that the milestone doesn't already exists
                # FIXME: the whole .exists business needs to be clarified
                #        (#4130) and should behave like a WikiPage does in
                #        this respect.
                try:
                    other_milestone = StructuredMilestone(self.env, new_name, db)
                    warn(_('Milestone "%(name)s" already exists, please '
                           'choose another name', name=new_name))
                except ResourceNotFound:
                    pass
        else:
            warn(_('You must provide a name for the milestone.'))

        # -- check completed date
        if action in MilestoneSystem(self.env).starting_action:
            milestone.ticket['started'] = str(to_timestamp(datetime.now(utc)))
        if action in MilestoneSystem(self.env).completing_action:
            milestone.completed = datetime.now(utc)
            
        if warnings:
            return self._render_editor(req, db, milestone)
        
        # -- actually save changes
        if milestone.exists:
            cnum = req.args.get('cnum')
            replyto = req.args.get('replyto')
            internal_cnum = cnum
            if cnum and replyto: # record parent.child relationship
                internal_cnum = '%s.%s' % (replyto, cnum)

            now = datetime.now(utc)
            milestone.save_changes(get_reporter_id(req, 'author'),
                                         req.args.get('comment'), when=now,
                                         cnum=internal_cnum)
            # eventually retarget opened tickets associated with the milestone
            if 'retarget' in req.args and completed:
                cursor = db.cursor()
                cursor.execute("UPDATE ticket SET milestone=%s WHERE "
                               "milestone=%s and status != 'closed'",
                                (retarget_to, old_name))
                self.env.log.info('Tickets associated with milestone %s '
                                  'retargeted to %s' % (old_name, retarget_to))
        else:
            milestone.insert()
        db.commit()

        add_notice(req, _('Your changes have been saved.'))
        jump_to = req.args.get('jump_to', 'roadmap')
        if jump_to=='roadmap':
            req.redirect(req.href.roadmap())
        elif jump_to =='whiteboard':
            req.redirect(req.href.whiteboard('team_tasks')+'#'+milestone.name)
        else:
            req.redirect(req.href.milestone(milestone.name))

        

    def _render_confirm(self, req, db, milestone):
        req.perm(milestone.resource).require('MILESTONE_DELETE')

        milestones = [m for m in Milestone.select(self.env, db=db)
                      if m.name != milestone.name
                      and 'MILESTONE_VIEW' in req.perm(m.resource)]
        data = {
            'milestone': milestone,
            'milestone_groups': group_milestones(milestones,
                'TICKET_ADMIN' in req.perm)
        }
        return 'milestone_delete.html', data, None

    def _render_editor(self, req, db, milestone):
        data = {
            'milestone': milestone,
            'ticket': milestone.ticket,
            'datefields' : self.date_fields,
            'date_hint': get_date_format_hint(),
            'datetime_hint': get_datetime_format_hint(),
            'milestone_groups': [],
        }

        if milestone.exists:
            req.perm(milestone.resource).require('MILESTONE_VIEW')
            milestones = [m for m in StructuredMilestone.select(self.env, db=db)
                          if m.name != milestone.name
                          and 'MILESTONE_VIEW' in req.perm(m.resource)]
            data['milestone_groups'] = group_milestones(milestones,
                'TICKET_ADMIN' in req.perm)
        else:
            req.perm(milestone.resource).require('MILESTONE_CREATE')

        TicketModule(self.env)._insert_ticket_data(req, milestone.ticket, data, 
                                         get_reporter_id(req, 'author'), {})
        self._add_tickets_report_data(milestone, req, data)
        context = Context.from_request(req, milestone.resource)
        
        data['attachments']=AttachmentModule(self.env).attachment_data(context)

        return 'itteco_milestone_edit.html', data, None
        
    def _add_tickets_report_data(self, milestone, req, data):
        tickets_report = MilestoneSystem(self.env).tickets_report
        if tickets_report:
            req.args['MILESTONE'] = milestone.name
            req.args['id']=tickets_report
            report_data = IttecoReportModule(self.env).get_report_data(req, tickets_report)
            self.env.log.debug('report_data="%s"' % (report_data,))
            data.update(report_data)
            
            debug = IttecoEvnSetup(self.env).debug
            
            add_jscript(req, 'stuff/plugins/jquery.rpc.js', debug)
            add_jscript(req, 'stuff/ui/plugins/jquery.jeditable.js', debug)
            add_jscript(req, 'stuff/ui/ui.core.js', debug)
            add_jscript(req, 'stuff/ui/ui.draggable.js', debug)
            add_jscript(req, 'stuff/ui/ui.droppable.js', debug)
            add_jscript(req, 'editable_report.js', debug)
            add_jscript(req, 'report.js', debug)
            #add_stylesheet(req, 'itteco/css/report.css')
            data['fields_config'] = IttecoReportModule(self.env).fields_dict(data.get('header_groups',[]))
        data['render_report'] = tickets_report or None

    # IWikiSyntaxProvider methods

    def get_wiki_syntax(self):
        return []

    def get_link_resolvers(self):
        yield ('milestone', self._format_link)

    def _format_link(self, formatter, ns, name, label):
        name, query, fragment = formatter.split_link(name)
        return self._render_link(formatter.context, name, label,
                                 query + fragment)

    def _render_link(self, context, name, label, extra=''):
        try:
            milestone = StructuredMilestone(self.env, name)
        except TracError:
            milestone = None
        # Note: the above should really not be needed, `Milestone.exists`
        # should simply be false if the milestone doesn't exist in the db
        # (related to #4130)
        href = context.href.milestone(name)
        if milestone and milestone.exists:
            if 'MILESTONE_VIEW' in context.perm(milestone.resource):
                closed = milestone.is_completed and 'closed ' or ''
                return tag.a(label, class_='%smilestone' % closed,
                             href=href + extra)
        elif 'MILESTONE_CREATE' in context.perm('milestone', name):
            return tag.a(label, class_='missing milestone', href=href + extra,
                         rel='nofollow')
        return tag.a(label, class_='missing milestone')
        
    # IResourceManager methods

    def get_resource_realms(self):
        yield 'milestone'

    def get_resource_description(self, resource, format=None, context=None,
                                 **kwargs):
        desc = resource.id
        if format != 'compact':
            desc =  _('Milestone %(name)s', name=resource.id)
        if context:
            return self._render_link(context, resource.id, desc)
        else:
            return desc

    # ISearchSource methods

    def get_search_filters(self, req):
        if 'MILESTONE_VIEW' in req.perm:
            yield ('milestone', _('Milestones'))

    def get_search_results(self, req, terms, filters):
        if not 'milestone' in filters:
            return
        db = self.env.get_db_cnx()
        sql_query, args = search_to_sql(db, ['name', 'description'], terms)
        cursor = db.cursor()
        cursor.execute("SELECT name,due,completed,description "
                       "FROM milestone "
                       "WHERE " + sql_query, args)

        milestone_realm = Resource('milestone')
        for name, due, completed, description in cursor:
            milestone = milestone_realm(id=name)
            if 'MILESTONE_VIEW' in req.perm(milestone):
                yield (get_resource_url(self.env, milestone, req.href),
                       get_resource_name(self.env, milestone),
                       datetime.fromtimestamp(
                           completed or due, utc),
                       '', shorten_result(description, terms))
        
        # Attachments
        for result in AttachmentModule(self.env).get_search_results(
            req, milestone_realm, terms):
            yield result
    
    # ITicketChangeListener methods
    def ticket_created(self, ticket):
        pass

    def ticket_changed(self, ticket, comment, author, old_values):
        old_summary = old_values.get('summary')
        if ticket['type']==milestone_ticket_type \
            and old_summary \
            and ticket['summary'] != old_summary:
                try:
                    milestone = Milestone(self.env, old_summary)
                    if milestone.exists:
                        milestone.name = ticket['summary']
                        milestone.update()
                except ResourceNotFound:
                    pass

    def ticket_deleted(self, ticket):
        pass
        
    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'structured_milestone'

    def xmlrpc_methods(self):
        yield (None, ((dict, dict),), self.create)
        yield (None, ((dict, str, str, dict),), self.update)

    def create(self, req, attributes):
        """ Create a structure milestone object."""
        name = attributes.get('summary')
        milestone = StructuredMilestone(self.env, name)
        if milestone.exists:
            raise TracError('Milestone already with name %s exists' % name)
        req.perm.require('MILESTONE_CREATE', Resource(milestone.resource.realm))
        milestone.description = attributes.get('description')
        for k, v in attributes.iteritems():
            milestone.ticket[k] = v
        milestone.insert()
        return {'name': milestone.name, 'description': milestone.description}
    
    def update(self, req, name, comment, attributes=None):
        """ Updates a structure milestone object."""
        milestone = StructuredMilestone(self.env, name)
        if not milestone.exists:
            raise TracError('Milestone with name %s does not exist' % name)
        req.perm.require('MILESTONE_CREATE', Resource(milestone.resource.realm))
        if attributes is not None:
            milestone.name = attributes.get('summary')
            milestone.description = attributes.get('description')
            for k, v in attributes.iteritems():
                milestone.ticket[k] = v
        milestone.save_changes(get_reporter_id(req, 'author'), comment)
        return {'name': milestone.name, 'description': milestone.description}
    
class IttecoRoadmapModule(RoadmapModule):
    _calculate_statistics_on = ListOption('itteco-roadmap-config', 'calc_stats_on', [])   
    _ticket_groups = (('scope_element', _('Scope Tickets')), ('work_element', _('Work Tickets')), ('all', _('All tickets')))
    
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
        ticket_group = req.args.get('ticket_group', 'all')
        selected_types = None
        if ticket_group=='scope_element':
            selected_types = IttecoEvnSetup(self.env).scope_element
        elif ticket_group=='work_element':
            selected_types = IttecoEvnSetup(self.env).work_element
        else:
            ticket_group = 'all'
            
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
        ticket_groups = [{'index':value, 'label': name, 'active': value==ticket_group} 
                for value, name in self._ticket_groups]
        
        calculate_on = self.get_statistics_source(req.args.get('calc_on'))
        data = {
            'milestones': milestones,
            'milestone_stats': stats,
            'mil_types': visibility,
            'ticket_groups': ticket_groups,
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