from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
import sys

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements, TracError
from trac.config import Option, ListOption, ExtensionOption
from trac.resource import ResourceNotFound, Resource
from trac.ticket.api import TicketSystem
from trac.ticket.default_workflow import ConfigurableTicketWorkflow
from trac.ticket.model import Ticket, Resolution, Type, Milestone
from trac.ticket.roadmap import apply_ticket_permissions, DefaultTicketGroupStatsProvider
from trac.ticket.web_ui import TicketModule

from trac.util import get_reporter_id
from trac.util.compat import set
from trac.util.datefmt import utc, to_timestamp, format_datetime
from trac.util.translation import _

from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import INavigationContributor, add_stylesheet

from tracrpc.api import IXMLRPCHandler

from itteco.init import IttecoEvnSetup
from itteco.scrum.api import ITeamMembersProvider
from itteco.scrum.burndown import IBurndownInfoProvider
from itteco.ticket.model import StructuredMilestone, TicketLinks, milestone_ticket_type
from itteco.ticket.utils import get_tickets_for_milestones, get_tickets_by_ids, get_tickets_by_filter
from itteco.utils import json
from itteco.utils.render import get_powered_by_sign, add_jscript
    
def _get_req_param(req, name, default=None):
    val = req.args.get(name)
    if val is None:
        val = req.session.get(name,default)
    else:
        req.session[name]=val
    return val
    
def _get_req_bool_param(req, name):
    val = _get_req_param(req, name)
    return val and val=='on' or False

class WhiteboardModule(Component):
    implements(INavigationContributor, IRequestHandler, IXMLRPCHandler)
    
    scope_element_weight_field = Option('itteco-whiteboard-tickets-config', 'scope_element_weight_field', 'business_value',
        "The ticket field that would be used for user story weight calculation")

    work_element_weight_field = Option('itteco-whiteboard-tickets-config', 'work_element_weight_field', 'complexity',
        "The ticket field that would be used for ticket weight calculation")
        
    team_members_provider = ExtensionOption('itteco-whiteboard-config', 'team_members_provider', ITeamMembersProvider,
        'ConfigBasedTeamMembersProvider',
        doc="The component implementing a team member provider interface.")

    burndown_info_provider = ExtensionOption('itteco-whiteboard-config', 'burndown_info_provider', IBurndownInfoProvider,
        'BuildBurndownInfoProvider',
        doc="The component implementing a burndown info provider interface.")

    _ticket_type_config = _old_ticket_config = _old_groups = _ticket_groups= None

    ticket_type_config = property(lambda self: self._get_ticket_config())
    ticket_groups = property(lambda self: self._get_ticket_groups())    
    transitions = property(lambda self: self._get_ticket_transitions())
        
    # INavigationContributor methods    
    def get_active_navigation_item(self, req):
        return 'whiteboard'

    def get_navigation_items(self, req):
        if 'TICKET_VIEW' in req.perm:
            yield ('mainnav', 'whiteboard', tag.a(_('Whiteboard'), href=req.href.whiteboard(), accesskey=4))

    # IRequestHandler methods
    def match_request(self, req):
        if req.path_info.startswith('/whiteboard'):
            path = req.path_info.split('/')
            path_len = len(path)
            if path_len>2:
                req.args['board_type'] = path[2]
            if path_len>3:
                req.args['milestone'] = path[3]
            return True

    def process_request(self, req):
        req.perm('ticket').require('TICKET_VIEW')
        
        board_type = req.args.get('board_type', 'team_tasks')
        milestone = req.args.get('milestone')
        if board_type == 'chart_settings':
            return self._chart_settings(milestone)
        else:
            board_type = _get_req_param(req, 'board_type', 'team_tasks')
            
            if board_type != req.args.get('board_type'):
                #boardtype was not implicitly  selected, let's restore previos state
                req.redirect(req.href.whiteboard(board_type, milestone))

            add_stylesheet(req, 'common/css/roadmap.css')
            add_stylesheet(req, 'itteco/css/common.css')            
            add_jscript(
                req, 
                [
                    'stuff/ui/ui.core.js',
                    'stuff/ui/ui.draggable.js',
                    'stuff/ui/ui.droppable.js',
                    'stuff/ui/ui.resizable.js',
                    'stuff/ui/plugins/jquery.colorbox.js',
                    'stuff/plugins/jquery.rpc.js',
                    'custom_select.js',
                    'whiteboard2.js'
                ],
                IttecoEvnSetup(self.env).debug
            )
            show_closed_milestones = req.args.get('show_closed_milestones', False)
            
            scope_item, work_item = self._get_wbitems_config(board_type)
            structured_milestones = StructuredMilestone.select(self.env, show_closed_milestones)
            if board_type == 'burndown':
                structured_milestones, _ignore = self._get_milestones_by_level(structured_milestones, 'Sprint', True)
            data ={
                'structured_milestones' : structured_milestones,
                'current_board_type' : board_type,
                'milestone' : milestone,
                'milestone_levels': IttecoEvnSetup(self.env).milestone_levels,
                'stats_config': self._get_stats_config(),
                'show_closed_milestones': show_closed_milestones,
                'wbconfig' : {
                    'rpcurl' : req.href.login("xmlrpc"),
                    'baseurl' : req.href(),
                    'workitem' : work_item,
                    'scopeitem': scope_item,
                    'groups': self.ticket_groups,
                    'transitions': self.transitions
                },
                'team' : self.team_members_provider and self.team_members_provider.get_team_members() or [],
                'ticket_types' : work_item['types'] or []
            }
                
            return 'itteco_whiteboard2.html', data, 'text/html'
    
    def _chart_settings(self, milestone):
        burndown_info = self.burndown_info_provider.metrics(milestone)
        mils =[]
        def flatten(mil):
            mils.append(mil)
            for kid in mil.kids:
                flatten(kid)
        flatten(StructuredMilestone(self.env, milestone))
        fmt_date = lambda x: format_datetime(x, '%Y-%m-%dT%H:%M:%S')
        cvs_data = graphs = events = None
        if burndown_info:
            metrics, graphs = burndown_info
            def get_color(tkt_type):
                tkt_cfg = self.ticket_type_config
                if tkt_cfg:
                    cfg = tkt_cfg.get(tkt_type)
                    if cfg:
                        return cfg.get('max_color')

            graphs = [{'name': graph, 'color': get_color(graph)} for graph in graphs]

            burndown_cvs_data = burnup_cvs_data = []
            keys = ['burndown', 'approximation', 'ideal']
            milestone_dates= dict([(mil.completed or mil.due, mil) for mil in mils ])
            events =[]
            prev_burndown = metrics[0]['burndown']
            prev_burnup = 0
            
            def genitems(metric):
                yield fmt_date(metric['datetime'])
                for key in keys:
                    yield str(metric.get(key,''))
                    
            for metric in metrics:
                ts = metric['datetime']
                line = ",".join(genitems(metric))
                burnup_sum = 0
                burnup = metric.get('burnup',[])
                for item in burnup:
                    burnup_sum -= item
                    line +=','+str(-1*item)
                if burnup:
                    line +=','+str(burnup_sum)
                burndown_cvs_data.append(line)

                if ts in milestone_dates:
                    mil = milestone_dates[ts]
                    if mil.is_completed:
                        del milestone_dates[ts]
                        burndown = metric['burndown']
                        events.append({'datetime': fmt_date(mil.completed),
                            'extended': True, 
                            'text': '"%s" completed\nBurndown delta %d\nBurnup delta %d.' \
                                % (mil.name, prev_burndown-burndown, prev_burnup-burnup_sum) ,
                            'url': self.env.abs_href('milestone',mil.name)})
                        burndown_delta =0
                        prev_burnup = burnup_sum
                        prev_burndown = burndown
            events.extend([{'datetime': fmt_date(mil.due),
                            'text': '"%s" is planned to be completed.' % mil.name ,
                            'url': self.env.abs_href('milestone',mil.name)} for mil in milestone_dates.itervalues()])
            cvs_data = "<![CDATA["+"\n".join(burndown_cvs_data)+"]]>"

        data = {'data': cvs_data, 'graphs': graphs, 'events': events}
        return 'iiteco_chart_settings.xml', data, 'text/xml'

    def _get_stats_config(self):
        all_statuses = set(TicketSystem(self.env).get_all_status())
        remaining_statuses = set(all_statuses)
        groups =  DefaultTicketGroupStatsProvider(self.env)._get_ticket_groups()
        catch_all_group = None

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
        
        return groups
        
    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'whiteboard'

    def xmlrpc_methods(self):
        yield (None, ((list,), (list,dict)), self.query)

    def query(self, req, context={}):
        """ Returns all tickets that are to be rendered on a whiteboard."""
        board = context.get('board', 'team_tasks')
        if board=='team_tasks':
            return self.query_tasks(req, context)
        elif board=='stories':
            return self.query_stories(req, context)
        
    def query_tasks(self, req, context):
        milestone_name = self._resolve_milestone(context.get('milestone'), context.get('show_sub_mils'), context.get('show_completed'))
       
        all_tkt_types = set([ticket_type.name for ticket_type in Type.select(self.env)])
        scope_tkt_types = set([t for t in IttecoEvnSetup(self.env).scope_element])
        workitem_tkt_types = all_tkt_types - scope_tkt_types \
            - set([t for t in IttecoEvnSetup(self.env).excluded_element])
        self.env.log.debug('workitem_tkt_types ="%s"' % (workitem_tkt_types,))
        
        roots, ticket_ids = self._get_tickets_graph(req, milestone_name, (scope_tkt_types , workitem_tkt_types))
        self.env.log.debug('roots ="%s"' % (roots,))
        empty_scope_element  = {'summary': 'Not assigned to any story'}
        not_assigned_work_items, _ignore = self._get_tickets_graph(req, milestone_name, (workitem_tkt_types,))

        for ticket in not_assigned_work_items:
            if ticket['id'] not in ticket_ids:
                empty_scope_element.setdefault('references', []).append(ticket)
        roots.append(empty_scope_element)
        return roots
        
    def query_stories(self, req, context):
        level = context.get('level')
        
        all_milestones = StructuredMilestone.select(self.env, True)
        mils, mils_dict = self._get_milestones_by_level(all_milestones, level, context.get('show_completed'))
        milestones = [mil.name for mil in mils] +['']
        fields = [
            'summary', 
            'description',
            'owner',
            self.scope_element_weight_field, 
            self.work_element_weight_field
        ]

        def milestone_as_dict(milestone):
            res = dict([(f, milestone.ticket[f]) for f in fields])
            res.update(
                {
                    'id': milestone.name,
                    'references': []
                }
            )
            return res
        empty_scope_element  = {'id': '', 'summary': 'Backlog (no milestone)','references': []}
        
        roots = [empty_scope_element] + [milestone_as_dict(m) for m in mils]
        milestone_by_name = dict([(m['id'], m) for m in roots])
       
        scope_tkt_types = set([t for t in IttecoEvnSetup(self.env).scope_element])       
        tickets, ticket_ids = self._get_tickets_graph(req, milestones, (scope_tkt_types,))
        
        self.env.log.debug('roots ="%s"' % (roots,))
        for ticket in tickets:
            root = milestone_by_name.get(ticket['milestone'],empty_scope_element)
            root['references'].append(ticket)
            
        return roots

    def _get_tickets_graph(self, req, milestones, type_groups):
        db = self.env.get_db_cnx()
        
        mils = isinstance(milestones, basestring) and [milestones] or list(milestones)
        if '' in mils:
            mils +=[None]

        all_requested_fields = \
            self._get_ticket_fields(
                [
                    'summary', 
                    'description',
                    'milestone',
                    'owner',
                    self.scope_element_weight_field, 
                    self.work_element_weight_field
                ]
            )
        all_ids = []
        roots = back_trace = None
        for types in type_groups:
            if roots is not None and not back_trace:
                #we do not have ids for none root of the graph
                break
                
            filters = {
                'milestone' : mils,
                'type' : types
            }
            
            if back_trace is not None:
                filters['id']= back_trace.keys()
                
            tickets = apply_ticket_permissions(
                self.env, req, get_tickets_by_filter(db, all_requested_fields, **filters))
                
            all_ids.extend([ticket['id'] for ticket in tickets])
            
            if roots is None:
                roots = list(tickets)
                
            if back_trace:
                for ticket in tickets:
                    referers = back_trace[ticket['id']]
                    if referers:
                        for referer in referers:
                            referer.setdefault('references',[]).append(ticket);

            back_trace = defaultdict(list)
            if tickets:
                tickets_by_id =dict((tkt['id'], tkt) for tkt in tickets)
                src_ids = tickets_by_id.keys()

                cursor = db.cursor()
                cursor.execute("SELECT dest, src FROM tkt_links WHERE dest IN (%s)" % (len(src_ids)*"%s,")[:-1], src_ids)
                for dest, src in cursor:
                    back_trace[src].append(tickets_by_id[dest])
        return roots, all_ids

    def _get_ticket_fields(self, names,  default = None):
        if not names:
            return default
        names = isinstance(names, basestring) and [name.strip() for name in names.split(',')] or names
        return [field for field in TicketSystem(self.env).get_ticket_fields() \
                                if field['name'] in names]
    
    def _resolve_milestone(self, name, include_kids, show_completed):
        def _flatten_and_get_names(mil, include_kids, show_completed):
            names= []
            if mil:
                mil = isinstance(mil, StructuredMilestone) and [mil,] or mil
                for m in mil:
                    if show_completed or not m.completed:
                        names.append(m.name)
                        if include_kids:
                            names.extend(_flatten_and_get_names(m.kids, include_kids, show_completed))
            return names
        if name=='nearest':
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute(
                'SELECT name FROM milestone WHERE due>%s ORDER BY due LIMIT 1', \
                (to_timestamp(datetime.now(utc)),))
            row = cursor.fetchone()
            name=row and row[0] or 'none'
        elif name=='not_completed_milestones':
            return _flatten_and_get_names(StructuredMilestone.select(self.env, False), \
                include_kids, show_completed)
        if name=='none':
            return ''
        try:    
            mil = StructuredMilestone(self.env, name)            
            names = _flatten_and_get_names(mil, include_kids, show_completed)
            if not names:
                names = mil.name
            return names
        except ResourceNotFound:
            return ''

    def _get_milestones_by_level(self, mils_tree, level_name, include_completed):
        mils =[]
        mils_dict={}
        def filter_mils(mil, force_add=False):
            mils_dict[mil.name] = mil
            if mil.level['label']==level_name:
                if not mil.is_completed or include_completed:
                    mils.append(mil)
                    for kid in mil.kids:
                        filter_mils(kid, True)
            else:
                for kid in mil.kids:
                    filter_mils(kid, force_add)
        
        for mil in mils_tree:
            filter_mils(mil)
            
        return (mils, mils_dict)
    
    def _get_wbitems_config(self, board_type):
        milestoneitem = {
            'realm' : 'milestone',
            'types' : [milestone_ticket_type],
            'weight': self.work_element_weight_field,
            'weightlabel' : 'CP'
        }
        scopeitem = {
            'realm' : 'ticket',
            'types' : [t for t in IttecoEvnSetup(self.env).scope_element],
            'weight': self.scope_element_weight_field,
            'weightlabel' : 'BV'
        }

        def read_options(fname):
            options = [ 
                f['options'] \
                for f in TicketSystem(self.env).get_ticket_fields() \
                if f['name']==fname
            ]
            if options:
                return options[0]
                
        workitem = {
            'realm' : 'ticket',
            'types' : [t for t in IttecoEvnSetup(self.env).work_element],
            'weight': self.work_element_weight_field,
            'weightlabel' : 'CP',
            'options' : read_options(self.work_element_weight_field)
        }
        
        if board_type=='team_tasks':
            return (scopeitem, workitem)
        else:
            return (milestoneitem, scopeitem)
            
    def _get_ticket_transitions(self):
        groups_config = self.env.config['itteco-whiteboard-groups']
        
        if self._old_groups!=groups_config or self._transitions is None:
            actions = ConfigurableTicketWorkflow(self.env).actions
            transitions = [
                {
                    'newstatus': act_info['newstate'], 
                    'action': act_id, 
                    'oldstatuses':act_info['oldstates']
                } \
                for act_id, act_info in actions.iteritems()
                    if act_id!='_reset'
            ]
            
            self.env.log.debug('transitions="%s"' % transitions)
            self._transitions = transitions
        return self._transitions
    
    def _get_ticket_config(self):
        ticket_config = self.env.config['itteco-whiteboard-tickets-config']
        if self._old_ticket_config!=ticket_config:
            default_fields = ticket_config.getlist('default_fields')
            show_workflow = ticket_config.getbool('show_workflow')

            allowed_tkt_types = [ type.name for type in Type.select(self.env)]
            _ticket_type_config = {}
            for option in ticket_config:
                try:
                    tkt_type, prop = option.split('.',1)
                    if tkt_type and ( tkt_type in allowed_tkt_types or \
                        tkt_type[0]=='$'):
                        _ticket_type_config.setdefault(
                            tkt_type, 
                            {
                                'fields'   : default_fields,
                                'workflow' : show_workflow
                            }
                        )[prop] = ticket_config.get(option)
                except ValueError :
                    pass

            scope_types = IttecoEvnSetup(self.env).scope_element
            scope_element_field_name = self.scope_element_weight_field
            
            work_types = IttecoEvnSetup(self.env).work_element
            work_element_field_name = self.work_element_weight_field
            
            for type in allowed_tkt_types:
                if type not in _ticket_type_config:
                    _ticket_type_config[type]={'fields':default_fields, 'workflow' : show_workflow}
            
            for type in _ticket_type_config.iterkeys():
                _ticket_type_config[type]['weight_field_name'] = \
                    type in scope_types and scope_element_field_name or work_element_field_name
                _ticket_type_config[type]['fields']=self._get_ticket_fields(
                    _ticket_type_config[type].get('fields'), [])
                    
            self._ticket_type_config = _ticket_type_config
            self._old_ticket_config=ticket_config
        return self._ticket_type_config
                
    def _get_ticket_fields(self, names,  default = None):
        if not names:
            return default
        names = isinstance(names, basestring) and [name.strip() for name in names.split(',')] or names
        return [field for field in TicketSystem(self.env).get_ticket_fields() \
                                if field['name'] in names]
    
    def _get_ticket_groups(self):
        groups_config = self.env.config['itteco-whiteboard-groups']
        
        if self._old_groups!=groups_config:
            self._transitions = None
            def get_group_options(group_name):
                opts ={'name': group_name}
                
                for options, accessor in [(('accordion',), groups_config.get), \
                                          (('status',),groups_config.getlist)]:
                    for opt in options:
                        opts[opt] = accessor('group.%s.%s' % (group_name, opt))
                return opts
                    
            self._old_groups=groups_config
            self._ticket_groups=[get_group_options(gr_name) 
                for gr_name in groups_config.getlist('groups', keep_empty=False)]
            
            self.env.log.debug('ticket_groups="%s"' % self._ticket_groups)
        return self._ticket_groups

    def get_new_ticket_descriptor(self, types, tkt_id=None):
        if tkt_id and tkt_id!='new':
            ticket = Ticket(self.env, tkt_id)
            if not ticket.exists:
                raise TracError(_(" Ticket with id '%(ticket)s does not exit", ticket= tkt_id))
            types = [ticket['type']]
        else:
            ticket = Ticket(self.env)
            ticket.id = 'new'
        common_descriptor = {'ticket' : ticket}

        if types:
            for type in types:
                cfg = self.ticket_type_config.get(type, {})
                common_descriptor.setdefault('fields',[]). \
                    extend(cfg.get('fields',[]))
                common_descriptor['workflow'] = common_descriptor.get('workflow',False) \
                    or cfg.get('workflow') or False
                    
            unique_fields = []
            found_names = []
            for field in common_descriptor['fields']:
                if field['name'] not in found_names:
                    found_names.append(field['name'])
                    unique_fields.append(field)
            common_descriptor['fields'] = unique_fields
        return common_descriptor
