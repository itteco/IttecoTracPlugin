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

from itteco.init import IttecoEvnSetup
from itteco.scrum.api import ITeamMembersProvider
from itteco.scrum.burndown import IBurndownInfoProvider
from itteco.ticket.model import StructuredMilestone, TicketLinks
from itteco.ticket.utils import get_tickets_for_milestones, get_tickets_by_ids
from itteco.utils import json
from itteco.utils.render import get_powered_by_sign, add_jscript

def add_whiteboard_ctxtnav(data, elm_or_label, href=None, **kwargs):
    """Add an entry to the whiteboard context navigation bar.
    """
    if href:
        elm = tag.a(elm_or_label, href=href, **kwargs)
    else:
        elm = elm_or_label
    data.setdefault('whitebord_ctxtnav', []).append(elm)
    
class dummy:
    summary='Not assigned to any story'
    status=id=name=None
    def __getitem__(self, name):
        return None

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

class DashboardModule(Component):
    implements(INavigationContributor, IRequestHandler, ITemplateStreamFilter)
    
    default_milestone_level = Option('itteco-whiteboard-config', 'default_milestone_level','Sprint',
        "The milestone level selected on storyboard by default.")

    scope_element_weight_field = Option('itteco-whiteboard-tickets-config', 'scope_element_weight_field', 'business_value',
        "The ticket field that would be used for user story weight calculation")

    work_element_weight_field = Option('itteco-whiteboard-tickets-config', 'work_element_weight_field', 'complexity',
        "The ticket field that would be used for ticket weight calculation")
        
    team_members_provider = ExtensionOption('itteco-whiteboard-config', 'team_members_provider',ITeamMembersProvider,
        'ConfigBasedTeamMembersProvider',
        doc="The component implementing a team member provider interface.")
    
    milestone_summary_fields = ListOption('itteco-whiteboard-config', 'milestone_summary_fields', ['business_value', 'complexity'],
        doc="The comma separated list of the ticket fields for which totals would be calculated within milestone widget on whiteboard.")    
    
    burndown_info_provider = ExtensionOption('itteco-whiteboard-config', 'burndown_info_provider',IBurndownInfoProvider,
        'BuildBurndownInfoProvider',
        doc="The component implementing a burndown info provider interface.")

    _ticket_type_config = _old_ticket_config = _old_groups = _ticket_groups= None
    
    ticket_groups = property(lambda self: self._get_ticket_groups())
    ticket_type_config = property(lambda self: self._get_ticket_config())
    
    def _get_empty_group(self):
        return dict(
            self.ticket_groups and \
            [(group['name'], []) for group in self.ticket_groups] or \
            [])
        
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
                    if tkt_type in allowed_tkt_types:
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
            scope_element_max_weight = self._get_max_weight(scope_element_field_name)
            
            work_types = IttecoEvnSetup(self.env).work_element
            work_element_field_name = self.work_element_weight_field
            work_element_max_weight = self._get_max_weight(work_element_field_name)
            
            for type in allowed_tkt_types:
                if type not in _ticket_type_config:
                    _ticket_type_config[type]={'fields':default_fields, 'workflow' : show_workflow}
                if type in scope_types:
                    _ticket_type_config[type].update({
                        'weight_field_name':scope_element_field_name, \
                        'max_weight':scope_element_max_weight})
                else:
                    _ticket_type_config[type].update({
                        'weight_field_name':work_element_field_name, \
                        'max_weight':work_element_max_weight})
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
            transitions = None
            if groups_config.getbool('use_workflow_configuration'):
                actions = ConfigurableTicketWorkflow(self.env).actions
                transitions = {}
                for act_id, act_info in actions.iteritems():
                    if act_id!='_reset':
                        transitions.setdefault(
                            act_info['newstate'], []). \
                                append({'action': act_id, 'oldstates':act_info['oldstates']}) 
                                
                self.env.log.debug('transitions="%s"' % transitions)
            def parse_transitions(transitions_string):
                pass# todo implement parsing
            def get_group_options(group_name, predefined_transitions):
                opts ={'name': group_name}
                
                for options, accessor in [(('accordion', 'transitions'),groups_config.get), \
                                          (('status',),groups_config.getlist)]:
                    for opt in options:
                        opts[opt] = accessor('group.%s.%s' % (group_name, opt))
                        
                if predefined_transitions:
                    if 'transitions' in opts:
                        del opts['transitions']
                    for ticket_status in opts['status']:
                        if ticket_status in predefined_transitions:
                            opts.setdefault('transitions', []).extend(predefined_transitions[ticket_status] or [])
                return opts
                    
            self._old_groups=groups_config
            self._ticket_groups=[get_group_options(gr_name, transitions) 
                for gr_name in groups_config.getlist('groups', keep_empty=False)]
            
            self.env.log.debug('ticket_groups="%s"' % self._ticket_groups)
        return self._ticket_groups
    
    def _get_ticket_group(self, ticket):
        for group in self.ticket_groups:
            statuses = group['status']
            statuses = (isinstance(statuses, tuple) or isinstance(statuses, list)) and statuses or (statuses,)
            if ticket['status'] in statuses:
                return group['name']
        return 'undefined'
    
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
        if board_type=='modify' and req.args.get('action'):
            self._perform_action(req)
        elif board_type == 'chart_settings':
            return self._chart_settings(req.args.get('milestone'))
        else:
            board_type = _get_req_param(req, 'board_type', 'team_tasks')
            add_stylesheet(req, 'common/css/roadmap.css')
            add_stylesheet(req, 'itteco/css/common.css')
            add_stylesheet(req, 'itteco/css/colorbox/colorbox.css')
            
            add_jscript(
                req, 
                [
                    'stuff/ui/ui.core.js',
                    'stuff/ui/ui.draggable.js',
                    'stuff/ui/ui.droppable.js',
                    'stuff/ui/ui.resizable.js',
                    'stuff/ui/plugins/fullcalendar.js',
                    'stuff/ui/plugins/jquery.jeditable.js',
                    'stuff/ui/plugins/jquery.colorbox.js',
                    'stuff/plugins/jquery.cookies.js',
                    'stuff/plugins/jquery.rpc.js',
                    'custom_select.js',
                    'whiteboard.js'
                ],
                IttecoEvnSetup(self.env).debug
            )
            
            if board_type != req.args.get('board_type'):
                #boardtype was not implicitly  selected, let's restore previos state
                req.redirect(req.href.whiteboard(board_type))
            data ={'board_type' : board_type,
                'stats_config': self._get_stats_config(),
                'groups': self.ticket_groups,
                'ticket_type_rendering_config': self.ticket_type_config,
                'show_closed_milestones':req.args.get('show_closed_milestones', False),
                'resolutions':[val.name for val in Resolution.select(self.env)],
                'team' : self.team_members_provider and self.team_members_provider.get_team_members() or []}
                
            for target, title in [('team_tasks', _('Team Tasks')), ('stories', _('Stories')), ('burndown', _('Burndown'))]:
                add_whiteboard_ctxtnav(data, title, req.href.whiteboard(target), class_= board_type==target and "active" or '')
                if board_type==target:
                    data['board_type_title'] = title

            if board_type=='stories':
                self._add_storyboard_data(req, data)
            elif board_type=='burndown':
                self._add_burndown_data(req, data)
            else:
                self._add_taskboard_data(req, data)
            return 'itteco_whiteboard.html', data, 'text/html'
    
    def _add_taskboard_data(self, req, data):
        board_type = req.args.get('board_type', 'team_tasks')
        milestone_name = _get_req_param(req, 'milestone', 'nearest')
        if milestone_name !=req.args.get('milestone'):
            req.redirect(req.href.whiteboard(board_type, milestone_name))
        
        show_closed_milestones = _get_req_bool_param(req, 'show_closed_milestones')
        include_sub_mils = _get_req_bool_param(req, 'include_sub_mils')

        milestone = self._resolve_milestone(milestone_name, include_sub_mils, show_closed_milestones)
        if (milestone and not isinstance(milestone, list) and milestone != milestone_name):
            req.redirect(req.href.whiteboard(board_type, milestone))
        add_jscript(req, 'taskboard.js', IttecoEvnSetup(self.env).debug)

        all_tkt_types = set([ticket.name for ticket in Type.select(self.env)])
               
        field = self._get_ticket_fields(self.work_element_weight_field)
        field = field and field[0] or self.work_element_weight_field
        data.update({'structured_milestones' : StructuredMilestone.select(self.env, show_closed_milestones),            
            'include_sub_mils':include_sub_mils,
            'show_closed_milestones':show_closed_milestones,
            'milestone': milestone,
            'table_title': _('User story\Ticket status'),
            'progress_field': field,
            'types': all_tkt_types,
            'row_head_renderer':'itteco_ticket_widget.html'})
            
        max_scope_item_weight = self._get_max_weight(self.scope_element_weight_field)
        max_work_item_weight = self._get_max_weight(self.work_element_weight_field)
        
        dummy_item = dummy()
        dummy_item.tkt = dummy_item
        wb_items = {dummy_item.id: {'scope_item': dummy_item}}
        def append_ticket(ticket, tkt_group, scope_item = dummy_item):
            id = scope_item['id']
            if not wb_items.has_key(id):
                wb_items[id] = self._get_empty_group()
                wb_items[id]['scope_item']=scope_item
            tkt_dict = {'ticket' : ticket}
            wb_items[id].setdefault(tkt_group, []).append(tkt_dict)
            
        active_tkt_types = (all_tkt_types | set([t for t in IttecoEvnSetup(self.env).scope_element])) - set([t for t in IttecoEvnSetup(self.env).excluded_element])
        for tkt_info in self._get_ticket_info(milestone, active_tkt_types, req=req, resolve_links=True):
            if tkt_info['type'] in IttecoEvnSetup(self.env).scope_element:
                sid = tkt_info['id']
                wb_items.setdefault(sid, self._get_empty_group())['scope_item']=tkt_info
                continue
            tkt_group = self._get_ticket_group(tkt_info)
            scope_item_found = False
            links = tkt_info.get('links')
            if links:
                for link_info in links:
                    if link_info['type'] in IttecoEvnSetup(self.env).scope_element:
                        scope_item_found = True
                        append_ticket(tkt_info, tkt_group, link_info)
                        break
            if not scope_item_found:
                append_ticket(tkt_info, tkt_group)
        data['wb_items'] = wb_items
        data['new_ticket_descriptor']= self.get_new_ticket_descriptor(
                IttecoEvnSetup(self.env).work_element)
        
        def mkey(x):
            f = self.scope_element_weight_field or 'id'
            key = x and x['id']
            try:
                key = key and (x[f] and -int(x[f]) or 1) or sys.maxint
            except:
                pass
            return key
                
        data['row_items_iterator']= sorted([s['scope_item'] for s in wb_items.values()], key=mkey)
            
    def _add_storyboard_data(self, req, data):
        add_jscript(req, 'storyboard.js', IttecoEvnSetup(self.env).debug)
        selected_mil_level = _get_req_param(req,'mil_level',self.default_milestone_level)
        
        mils_tree = StructuredMilestone.select(self.env, True)
        mils, mils_dict = self._get_milestones_by_level(mils_tree, selected_mil_level)
        milestone = [mil.name for mil in mils] +['']

        dummy_mil = dummy()
        dummy_mil.name=dummy_mil.summary = ''
        field = self._get_ticket_fields(self.scope_element_weight_field)
        field = field and field[0] or self.work_element_weight_field
        
        data.update({'milestones' : mils,
            'structured_milestones' : mils_tree,
            'milestone': milestone,
            'milestone_levels': [{'name': name, 'selected': name==selected_mil_level} for name in IttecoEvnSetup(self.env).milestone_levels],
            'table_title': _('Milestone\User story status'),
            'progress_field':  field,
            'row_items_iterator': mils+[dummy_mil],
            'row_head_renderer':'itteco_milestone_widget.html'})

        max_scope_item_weight = self._get_max_weight(self.scope_element_weight_field)
        
        milestone_sum_fields=self._get_ticket_fields(self.milestone_summary_fields)
        wb_items = dict()
        def get_root_milestone(mil):
            m = mils_dict.get(mil)
            while m and m.level['label']!=selected_mil_level and m.parent:
                m = mils_dict.get(m.parent)
            return m and m.name or ''
        def append_ticket(ticket, tkt_group, group_name):
            id = group_name or None
            if not wb_items.has_key(id):
                wb_items[id] = self._get_empty_group()
                wb_items[id]['fields']=milestone_sum_fields
            tkt_dict = {'ticket' : ticket}
            wb_items[id].setdefault(tkt_group, []).append(tkt_dict)
            
        for tkt_info in self._get_ticket_info(milestone, IttecoEvnSetup(self.env).scope_element, req):
            tkt_group = self._get_ticket_group(tkt_info)
            append_ticket(tkt_info, tkt_group, get_root_milestone(tkt_info['milestone']))
            
        for mil in milestone:
            if not wb_items.has_key(mil):
                wb_items[mil] = {'fields':milestone_sum_fields}
        data['new_ticket_descriptor'] = self.get_new_ticket_descriptor(
            IttecoEvnSetup(self.env).scope_element)

        data['wb_items'] = wb_items
    
    def _get_milestones_by_level(self, mils_tree, level_name, include_completed = False):
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
        
    def _resolve_milestone(self, name, include_kids = False, show_completed = False):
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
            
    def _perform_action(self, req):
        action = req.args['action']
        ticket_id = req.args['ticket']
        ticket = None
        if ticket_id=='new':
            ticket = Ticket(self.env)
            assert 'TICKET_CREATE' in req.perm(ticket.resource), 'No permission to create tickets.'
        else:
            ticket = Ticket(self.env, ticket_id)
            assert ticket.exists, 'Ticket should exist'
            assert 'TICKET_CHGPROP' in req.perm(ticket.resource), 'No permission to change ticket fields.'
        data = {'result':'done'}
        db = self.env.get_db_cnx()
        if action=='change_task':
            tkt_action = req.args.get('tkt_action')
            comment = req.args.get('comment')
            TicketModule(self.env)._populate(req, ticket)
            data.update(dict([(k[6:],v) for k,v in req.args.items() if k.startswith('field_')]));
            if tkt_action:
                actions = TicketSystem(self.env).get_available_actions(req, ticket)
                if tkt_action not in actions:
                    raise TracError(_('Invalid action "%(name)s"', name=tkt_action))
                owner_attr = 'action_%s_reassign_owner' % tkt_action
                if not req.args.has_key(owner_attr):
                    req.args[owner_attr]= req.authname != 'anonymous' and req.authname or ticket['owner']                
                field_changes, problems = TicketModule(self.env).get_ticket_changes(req, ticket, tkt_action)
                if problems:
                    raise TracError('Action execution failed "%s"' % problems)
                if field_changes:
                    TicketModule(self.env)._apply_ticket_changes(ticket, field_changes)
                    for key in field_changes:
                        data[key] = ticket[key]
                data['status'] = ticket['status']
            if ticket.exists:
                ticket.save_changes(get_reporter_id(req, 'author'), comment, db=db)
            else:
                ticket['status']='new'
                ticket['reporter']=get_reporter_id(req, 'author')
                ticket.insert(db=db)
                data['status']=ticket['status']
                data['ticket']=ticket.id
            
            new_story = req.args.get('new_story')
            old_story = req.args.get('old_story')
            if old_story != new_story:
                tkt_link = TicketLinks(self.env, ticket)
                if old_story:
                    tkt_link.outgoing_links.remove(int(old_story))
                if new_story:
                    tkt_link.outgoing_links.add(new_story)
                tkt_link.save(db=db)

        db.commit()
        req.write('(%s)' % json.write(data))
        
    def _get_ticket_info(self, milestones, types= None, req=None, resolve_links=True):
        db = self.env.get_db_cnx()
        mils = isinstance(milestones, basestring) and [milestones] or list(milestones)
        if '' in mils:
            mils +=[None]

        all_requested_fields = [ field \
            for tkt_type_cfg in self.ticket_type_config.values() \
                for field in tkt_type_cfg.get('fields',[])]  + \
            self._get_ticket_fields(['summary', 'description','milestone','resolution'])

        tkts_info = apply_ticket_permissions(
            self.env, req, get_tickets_for_milestones(db,  mils, all_requested_fields, types))
        
        if resolve_links and tkts_info:
            ticket_by_id =dict([tkt['id'], tkt] for tkt in tkts_info)
            src_ids = ticket_by_id.keys()
            cursor = db.cursor()
            cursor.execute("SELECT src, dest FROM tkt_links WHERE src IN (%s)" % (len(src_ids)*"%s,")[:-1], src_ids)
            links_dict = {}
            for src, dest in cursor:
                links_dict.setdefault(dest, []).append(src)
            if links_dict:#we found referenced tickets, lets resolve them
                refered_tickets_infos = apply_ticket_permissions(
                    self.env, req, get_tickets_by_ids(db, all_requested_fields, links_dict.keys()))
                for refered_ticket_info in refered_tickets_infos:
                    referers = links_dict[refered_ticket_info['id']]
                    if referers:
                        for ref_id in referers:
                            ticket_by_id[ref_id].setdefault('links',[]).append(refered_ticket_info);
        return tkts_info

    def _get_max_weight(self, field_name, default = 0):
        result = default;
        for field in TicketSystem(self.env).get_ticket_fields():
            if field['name']==field_name:
                for option in field['options']:
                    try:
                        int_option = int(option)
                        if int_option>result:
                            result = int_option
                    except:
                        pass
                break
        return result

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
    
    # Burndown related methods
    def _add_burndown_data(self, req, data):
        add_jscript(req, 'stuff/swfobject.js', IttecoEvnSetup(self.env).debug)
        mils_tree = StructuredMilestone.select(self.env, True)
        show_closed_milestones = _get_req_bool_param(req, 'show_closed_milestones')
        mils, mils_dict = self._get_milestones_by_level(mils_tree, 'Sprint', show_closed_milestones)
        for mil in mils:
            mil.kids = []
        current_milestone = _get_req_param(req,'milestone')
        del data['team']
        data['show_closed_milestones']=show_closed_milestones
        data['milestone'] = current_milestone
        data['milestones'] = mils
        data['structured_milestones'] = mils
        data['burndown'] = 1
        
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
            for metric in metrics:
                ts = metric['datetime']
                line = ",".join([fmt_date(ts)]+[str(metric.get(key,'')) for key in keys])
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

    #ITemplateStreamFilter methods, just add signature to the footer
    def filter_stream(self, req, method, filename, stream, data):
        if req.path_info.startswith('/whiteboard'):
            data['transformed']=1
            stream |=Transformer('//*[@id="footer"]/p[@class="right"]').before(get_powered_by_sign())
      
        return  stream
               
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
                cfg = self.ticket_type_config[type]
                
                common_descriptor.setdefault('fields',[]). \
                    extend(cfg.get('fields',[]))
                    
                common_descriptor['workflow'] = common_descriptor.get('workflow',False) or cfg.get('workflow') or False
                    
            extra_types = self._get_ticket_fields(['summary','description','type'])
            if extra_types:
                ticket_type_field = extra_types[-1]
                if ticket_type_field['type'] =='select':
                    ticket_type_field['options'] = [o for o in ticket_type_field['options'] if o in types]
            all_fields = extra_types + common_descriptor['fields']
            unique_fields = []
            found_names = []
            for field in all_fields:
                if field['name'] not in found_names:
                    found_names.append(field['name'])
                    unique_fields.append(field)
            common_descriptor['fields'] = unique_fields
        return common_descriptor
