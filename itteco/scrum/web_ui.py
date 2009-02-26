from datetime import datetime
import sys
from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements, TracError
from trac.config import Option, ListOption, ExtensionOption
from trac.ticket.roadmap import apply_ticket_permissions
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket, Resolution, Type, Milestone
from trac.ticket.web_ui import TicketModule
from trac.ticket.roadmap import DefaultTicketGroupStatsProvider

from trac.util import get_reporter_id
from trac.util.compat import set
from trac.util.translation import _
from trac.util.datefmt import utc, to_timestamp

from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import INavigationContributor, add_script, add_stylesheet

from itteco.init import IttecoEvnSetup
from itteco.scrum.api import ITeamMembersProvider
from itteco.ticket.model import StructuredMilestone, TicketLinks
from itteco.ticket.utils import get_tickets_for_milestones, get_tickets_by_ids
from itteco.utils import json
from itteco.utils.render import get_powered_by_sign

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

class DashboardModule(Component):
    implements(INavigationContributor, IRequestHandler, ITemplateStreamFilter)
    
    default_milestone_level = Option('itteco-whiteboard-config', 'default_milestone_level','Sprint',
        "The milestone level selected on storyboard by default.")

    scope_element = ListOption('itteco-whiteboard-tickets-config', 'scope_element', ['story'],
        doc="All tickets in a whiteboard would be grouped accorging their tracibility to this type of ticket")

    scope_element_weight_field = Option('itteco-whiteboard-tickets-config', 'scope_element_weight_field', 'business_value',
        "The ticket field that would be used for user story weight calculation")

    excluded_element = ListOption('itteco-whiteboard-tickets-config', 'excluded_element', [],
        doc="List of the ticket types, which should be excluded from the whiteboard.")

    work_element_weight_field = Option('itteco-whiteboard-tickets-config', 'work_element_weight_field', 'complexity',
        "The ticket field that would be used for ticket weight calculation")
        
    team_members_provider = ExtensionOption('itteco-whiteboard-config', 'team_members_provider',ITeamMembersProvider,
        'ConfigBasedTeamMembersProvider',
        doc="The component implementing a team member provider interface.")
    
    milestone_summary_fields = ListOption('itteco-whiteboard-config', 'milestone_summary_fields', ['business_value', 'complexity'],
        doc="The comma separated list of the ticket fields for which totals would be calculated within milestone widget on whiteboard.")    
    
    _ticket_type_config = _old_ticket_config = _old_groups = _ticket_groups= None
    
    ticket_groups = property(lambda self: self._get_ticket_groups())
    ticket_type_config = property(lambda self: self._get_ticket_config())
    
    def _get_empty_group(self):
        res = {}
        if self.ticket_groups:
            for group in self.ticket_groups:
                res[group['name']] = []
        return res
        
    def _get_ticket_config(self):
        ticket_config = self.env.config['itteco-whiteboard-tickets-config']
        if self._old_ticket_config!=ticket_config:
            default_fields = ticket_config.getlist('default_fields')

            types = [ type.name for type in Type.select(self.env)]
            self.env.log.debug("ticket_config-types '%s'" % types)
            _ticket_type_config = {}
            for option in ticket_config:
                try:
                    tkt_type, prop = option.split('.',1)
                    if tkt_type in types:
                        _ticket_type_config.setdefault(tkt_type, {'fields':default_fields})[prop] = ticket_config.get(option)
                except ValueError :
                    pass

            keys =  _ticket_type_config.keys()
            for type in types:
                if type not in keys:
                    _ticket_type_config[type]={'fields':default_fields}

            for key in  _ticket_type_config.keys():
                _ticket_type_config[key]['fields']=self._get_ticket_fields(_ticket_type_config[key].get('fields'))
                    
            self._ticket_type_config = _ticket_type_config
            self._old_ticket_config=ticket_config
        return self._ticket_type_config
        
    def _get_all_requested_fields(self):
        all = [ f for cfg in self.ticket_type_config.values() for f in cfg.get('fields')]  + \
            self._get_ticket_fields(['summary', 'description','milestone','resolution'])
        field_dict = {}
        for field in all:
            field_dict[field['name']]=field
        return field_dict.values()
        
    def _get_ticket_fields(self, names,  default = None):
        if not names:
            return default
        names = isinstance(names, basestring) and [name.strip() for name in names.split(',')] or names
        return [field for field in TicketSystem(self.env).get_ticket_fields() \
                                if field['name'] in names]

    def _get_ticket_groups(self):
        groups_config = self.env.config['itteco-whiteboard-groups']
        if self._old_groups!=groups_config:
            def get_group_options(group):
                opts ={'name': group}
                for options, accessor in [(('action', 'accordion'),groups_config.get), \
                                          (('status','source_status'),groups_config.getlist)]:
                    for opt in options:
                        opts[opt] = accessor('group.%s.%s' % (group, opt))
                return opts
            self._old_groups=groups_config
            self._ticket_groups=[get_group_options(gr_name) for gr_name in groups_config.getlist('groups', keep_empty=False)]
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

        add_stylesheet(req, 'css/roadmap.css')
        add_stylesheet(req, 'itteco/css/common.css')

        add_script(req, 'itteco/js/jquery.ui/ui.core.js')
        add_script(req, 'itteco/js/jquery.ui/ui.draggable.js')
        add_script(req, 'itteco/js/jquery.ui/ui.droppable.js')
        add_script(req, 'itteco/js/custom_select.js')
        add_script(req, 'itteco/js/whiteboard.js')
        
        board_type = req.args.get('board_type', 'team_tasks')
        if board_type=='modify':
            self._perform_action(req)
        else:    
            data ={'board_type' : board_type,
                'stats_config': self._get_stats_config(),
                'groups': self.ticket_groups,
                'resolutions':[val.name for val in Resolution.select(self.env)],
                'team' : self.team_members_provider and self.team_members_provider.get_team_members() or []}
                
            for target, title in [('team_tasks', _('Team Tasks')), ('stories', _('Stories'))]:
                add_whiteboard_ctxtnav(data, title, req.href.whiteboard(target), class_= board_type==target and "active" or '')
                if board_type==target:
                    data['board_type_title'] = title

            if board_type=='stories':
                self._add_storyboard_data(req, data)
            else:
                self._add_taskboard_data(req, data)
            return 'itteco_whiteboard.html', data, 'text/html'

    def _add_taskboard_data(self, req, data):
        board_type = req.args.get('board_type', 'team_tasks')
        milestone_name = req.args.get('milestone', 'nearest')
        
        show_closed_milestones = req.args.get('show_closed_milestones', False)
        include_sub_mils = req.args.get('include_sub_mils', False)

        milestone = self._resolve_milestone(milestone_name, include_sub_mils)
        if milestone and not isinstance(milestone, list) and milestone != milestone_name:
            req.redirect(req.href.whiteboard(board_type, milestone))
            
        add_script(req, 'itteco/js/taskboard.js')

        all_tkt_types = set([ticket.name for ticket in Type.select(self.env)])
               
        field = self._get_ticket_fields(self.work_element_weight_field)
        field = field and field[0] or self.work_element_weight_field
        data.update({'milestones' : StructuredMilestone.select(self.env, show_closed_milestones),
            'show_closed_milestones':show_closed_milestones,
            'include_sub_mils':include_sub_mils,
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
                self._add_rendering_properties(scope_item['type'], self.scope_element_weight_field, max_scope_item_weight, wb_items[id])
            tkt_dict = {'ticket' : ticket}
            self._add_rendering_properties(ticket['type'], self.work_element_weight_field, max_work_item_weight, tkt_dict)
            wb_items[id].setdefault(tkt_group, []).append(tkt_dict)
            
        active_tkt_types = (all_tkt_types | set([t for t in self.scope_element])) - set([t for t in self.excluded_element])
        for tkt_info in self._get_ticket_info(milestone, active_tkt_types, req=req, resolve_links=True):
            if tkt_info['type'] in self.scope_element:
                sid = tkt_info['id']
                wb_items.setdefault(sid, self._get_empty_group())['scope_item']=tkt_info
                self._add_rendering_properties(tkt_info['type'], self.scope_element_weight_field, max_scope_item_weight, wb_items[sid])
                continue
            tkt_group = self._get_ticket_group(tkt_info)
            scope_item_found = False
            links = tkt_info.get('links')
            if links:
                for link_info in links:
                    if link_info['type'] in self.scope_element:
                        scope_item_found = True
                        append_ticket(tkt_info, tkt_group, link_info)
                        break
            if not scope_item_found:
                append_ticket(tkt_info, tkt_group)
        data['wb_items'] = wb_items
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
        add_script(req, 'itteco/js/storyboard.js')
        
        selected_mil_level = req.args.get('mil_level',self.default_milestone_level)
        mils, mils_dict = self._get_milestones_by_level(selected_mil_level)
        milestone = mils_dict.keys()
        milestone.insert(0,'')

        dummy_mil = dummy()
        dummy_mil.name=dummy_mil.summary = ''
        field = self._get_ticket_fields(self.scope_element_weight_field)
        field = field and field[0] or self.work_element_weight_field
        
        data.update({'milestones' : mils,            
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
            self._add_rendering_properties(ticket['type'], self.scope_element_weight_field, max_scope_item_weight, tkt_dict)
            wb_items[id].setdefault(tkt_group, []).append(tkt_dict)
            
        for tkt_info in self._get_ticket_info(milestone, self.scope_element, req):
            tkt_group = self._get_ticket_group(tkt_info)
            append_ticket(tkt_info, tkt_group, get_root_milestone(tkt_info['milestone']))
            
        for mil in milestone:
            if not wb_items.has_key(mil):
                wb_items[mil] = {'fields':milestone_sum_fields}
        data['wb_items'] = wb_items
    
    def _get_milestones_by_level(self, level_name):
        mils =[]
        mils_dict={}
        def filter_mils(mil, force_add=False):
            mils_dict[mil.name] = mil
            if mil.level['label']==level_name:
                if not mil.is_completed:
                    mils.append(mil)
                    for kid in mil.kids:
                        filter_mils(kid, True)
            else:
                for kid in mil.kids:
                    filter_mils(kid, force_add)
                
        mils_tree = StructuredMilestone.select(self.env, True)
        for mil in mils_tree:
            filter_mils(mil)
            
        return (mils, mils_dict)
        
    def _resolve_milestone(self, name, include_kids = False):
        def _flatten_and_get_names(mil, include_kids):
            names= []
            if mil:
                mil = isinstance(mil, StructuredMilestone) and [mil,] or mil
                for m in mil:
                    names.append(m.name)
                    if include_kids:
                        names.extend(_flatten_and_get_names(m.kids, include_kids))
            return names
        if name=='nearest':
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute('SELECT name FROM milestone WHERE due>%s ORDER BY due LIMIT 1', (to_timestamp(datetime.now(utc)),))
            row = cursor.fetchone()
            name=row and row[0] or 'none'
        elif name=='not_completed_milestones':
            return _flatten_and_get_names(StructuredMilestone.select(self.env, False), include_kids)
        if name=='none':
            return ''
        return _flatten_and_get_names(StructuredMilestone(self.env, name), include_kids)
            
        
            
    def _perform_action(self, req):
        action = req.args['action']
        ticket = Ticket(self.env, req.args['ticket'])
        assert ticket.exists, 'Ticket should exist'
        assert 'TICKET_CHGPROP' in req.perm(ticket.resource), 'No permission to change ticket fields.'
        data = {'result':'done'}
        db = self.env.get_db_cnx()
        if action=='change_task':
            tkt_action = req.args.get('tkt_action')
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
            ticket.save_changes(get_reporter_id(req, 'author'), None, db=db)
            
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
        tkts_info = get_tickets_for_milestones(db,  mils, self._get_all_requested_fields(), types)
        tkts_info = apply_ticket_permissions(self.env, req, tkts_info)
        if resolve_links and tkts_info:
            tkts_dict =dict([t['id'], t] for t in tkts_info)
            src_ids = tkts_dict.keys()
            cursor = db.cursor()
            cursor.execute("SELECT src, dest FROM tkt_links WHERE src IN (%s)" % (len(src_ids)*"%s,")[:-1], src_ids)
            links_dict = {}
            for src, dest in cursor:
                links_dict.setdefault(dest, []).append(src)
            if links_dict:
                linked_infos = get_tickets_by_ids(db, self._get_all_requested_fields(), links_dict.keys())
                linked_infos = apply_ticket_permissions(self.env, req, linked_infos)
                for linked_info in linked_infos:
                    referers = links_dict[linked_info['id']]
                    if referers:
                        for ref_id in referers:
                            tkts_dict[ref_id].setdefault('links',[]).append(linked_info);
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

    def _add_rendering_properties(self, ticket_type, field_name, max_weight, props):
        tkt_cfg = self.ticket_type_config
        if tkt_cfg:
            cfg = tkt_cfg.get(ticket_type)
            if cfg:
                props['weight_field_name']=field_name
                props['max_weight']=max_weight
                props.update(cfg)

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
        
    def filter_stream(self, req, method, filename, stream, data):
        if req.path_info.startswith('/whiteboard'):
            data['transformed']=1
            stream |=Transformer('//*[@id="footer"]/p[@class="right"]').before(get_powered_by_sign())
      
        return  stream