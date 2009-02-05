from datetime import datetime
from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements, TracError
from trac.config import Option, ListOption
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket, Resolution, Type, Milestone
from trac.ticket.web_ui import TicketModule
from trac.ticket.roadmap import DefaultTicketGroupStatsProvider

from trac.util import get_reporter_id
from trac.util.compat import set
from trac.util.translation import _
from trac.util.datefmt import utc, to_timestamp

from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import INavigationContributor, add_script

from itteco.ticket.model import StructuredMilestone, TicketLinks
from itteco.utils import json
from itteco.utils.render import get_powered_by_sign

def add_whiteboard_ctxtnav(data, elm_or_label, href=None, title=None):
    """Add an entry to the whiteboard context navigation bar.
    """
    if href:
        elm = tag.a(elm_or_label, href=href, title=title)
    else:
        elm = elm_or_label
    data.setdefault('whitebord_ctxtnav', []).append(elm)
    
def tree_iteraror(roots, kids_attr='kids'):
    for root in roots:
        yield root
        for kid in tree_iteraror(getattr(root, kids_attr, []), kids_attr):
            yield kid

class dummy:
    summary='Not assigned to any story'
    status=id=name=None
    def __getitem__(self, name):
        return None

class DashboardModule(Component):
    implements(INavigationContributor, IRequestHandler, ITemplateStreamFilter)

    user_story_weight_field = Option('itteco-whiteboard-tickets-config', 'user_story_weight_field', 'business_value',
        "The ticket field that would be used for user story weight calculation")

    task_weight_field = Option('itteco-whiteboard-tickets-config', 'task_weight_field', 'complexity',
        "The ticket field that would be used for ticket weight calculation")

    user_story_ticket_type = Option('itteco-whiteboard-tickets-config', 'user_story_ticket_type', 'story',
        "All tickets in a whiteboard would be grouped accorging their tracibility to this type of ticket")
    
    team = ListOption('itteco-whiteboard-config', 'team',[],
        doc="The comma separated list of the team memebers. Is used on whiteboard.")
    
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
                
            def get_color(c):
                if c:                
                    rgb = [int(i) for i in c.split(',',3)]
                    rgb.extend((0,)*(3-len(rgb)))
                    return rgb
            keys =  _ticket_type_config.keys()
            for type in types:
                if type not in keys:
                    _ticket_type_config[type]={'fields':default_fields}

            for key in  _ticket_type_config.keys():
                for prop, func in [('fields',self._get_ticket_fields),]:#('min_color',get_color),('max_color', get_color)]:
                    _ticket_type_config[key][prop]=func(_ticket_type_config[key].get(prop))
                    
            self._ticket_type_config = _ticket_type_config
            self._old_ticket_config=ticket_config
        return self._ticket_type_config
        
    def _get_ticket_fields(self, names,  default = None):
        if not names:
            return default
        names = isinstance(names, basestring) and [name.strip() for name in names.split(',')] or names
        self.env.log.debug("Getting ticket fields for whiteboard '%s'" % names)
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

        board_type = req.args.get('board_type', 'my_tasks')
        if board_type=='modify':
            self._perform_action(req)
        else:    
            data ={'board_type' : board_type,
                'stats_config': self._get_stats_config(),
                'groups': self.ticket_groups,
                'resolutions':[val.name for val in Resolution.select(self.env)],
                'team' : self.team}
                
            for target, title in [('my_tasks', _('My Tasks')), ('team_tasks', _('Team Tasks')), ('stories', _('Stories'))]:
                add_whiteboard_ctxtnav(data, title, board_type!=target and req.href.whiteboard(target) or None)
                if board_type==target:
                    data['board_type_title'] = title

            if board_type=='stories':
                self._add_storyboard_data(req, data)
            else:
                self._add_taskboard_data(req, data)
            return 'itteco_whiteboard.html', data, 'text/html'

    def _add_taskboard_data(self, req, data):
        board_type = req.args.get('board_type', 'my_tasks')
        milestone_name = req.args.get('milestone', 'nearest')
        
        milestone = self._resolve_milestone(milestone_name)
        if milestone and not isinstance(milestone, list) and milestone != milestone_name:
            req.redirect(req.href.whiteboard(board_type, milestone))
        
        add_script(req, 'itteco/js/taskboard.js')
        show_closed_milestones = req.args.get('show_closed_milestones', False)
        field = self._get_ticket_fields(self.task_weight_field)
        field = field and field[0] or self.task_weight_field
        data.update({'milestones' : StructuredMilestone.select(self.env, show_closed_milestones),
            'show_closed_milestones':show_closed_milestones,
            'milestone': milestone,
            'table_title': _('User story\Ticket status'),
            'progress_field': field,
            'row_head_renderer':'itteco_ticket_widget.html'})
            
        max_story_weight = self._get_max_weight(self.user_story_weight_field)
        max_task_weight = self._get_max_weight(self.task_weight_field)
        
        dummy_story = dummy()
        dummy_story.tkt = dummy_story
        user_stories = {dummy_story.id: {'story': dummy_story}}
        def append_ticket(ticket, tkt_group, story = dummy_story):
            id = story.tkt.id
            if not user_stories.has_key(id):
                user_stories[id] = self._get_empty_group()
                user_stories[id]['story']=story
                self._add_rendering_properties(story, self.user_story_weight_field, max_story_weight, user_stories[id])
            tkt_dict = {'ticket' : ticket}
            self._add_rendering_properties(ticket, self.task_weight_field, max_task_weight, tkt_dict)
            user_stories[id].setdefault(tkt_group, []).append(tkt_dict)
            
        for tkt_id in self._get_ticket_ids(milestone, userfilter=(board_type=='my_tasks' and get_reporter_id(req) or None)):
            linked_ticket = TicketLinks(self.env, tkt_id)
            tkt_group = self._get_ticket_group(linked_ticket.tkt)
            story_found = False
            links = linked_ticket.outgoing_links
            if links:
                for i_link in links:
                    i_link_ticket = TicketLinks(self.env, i_link)
                    if i_link_ticket.tkt['type']==self.user_story_ticket_type:
                        story_found = True
                        append_ticket(linked_ticket, tkt_group, i_link_ticket)
            if not story_found:
                append_ticket(linked_ticket, tkt_group)
        for story_id in self._get_ticket_ids(milestone, True):
            if not user_stories.has_key(story_id):
                story = TicketLinks(self.env, story_id)
                user_stories.setdefault(story_id, self._get_empty_group())['story']=story
                self._add_rendering_properties(story, self.user_story_weight_field, max_story_weight, user_stories[story_id])
        data['stories'] = user_stories
        data['row_items_iterator']= sorted([s['story'].tkt for s in user_stories.values()], key=lambda x: x and x.id or -1)

            
    def _add_storyboard_data(self, req, data):
        add_script(req, 'itteco/js/storyboard.js')
        milestone = self._resolve_milestone('not_completed_milestones')
        milestone.insert(0,'')
        mils = StructuredMilestone.select(self.env, False)
        dummy_mil = dummy()
        dummy_mil.name=dummy_mil.summary = ''
        field = self._get_ticket_fields(self.user_story_weight_field)
        field = field and field[0] or self.task_weight_field

        data.update({'milestones' : mils,            
            'milestone': milestone,
            'table_title': _('Milestone\User story status'),
            'progress_field':  field,
            'row_items_iterator': tree_iteraror([dummy_mil,]+mils),
            'row_head_renderer':'itteco_milestone_widget.html'})

        max_story_weight = self._get_max_weight(self.user_story_weight_field)
        
        milestone_sum_fields=self._get_ticket_fields(self.milestone_summary_fields)
        user_stories = dict()        
        def append_ticket(ticket, tkt_group, group_name):
            id = group_name or None
            if not user_stories.has_key(id):
                user_stories[id] = self._get_empty_group()
                user_stories[id]['fields']=milestone_sum_fields
            tkt_dict = {'ticket' : ticket}
            self._add_rendering_properties(ticket, self.user_story_weight_field, max_story_weight, tkt_dict)
            user_stories[id].setdefault(tkt_group, []).append(tkt_dict)
            
        for tkt_id in self._get_ticket_ids(milestone, True):
            linked_ticket = TicketLinks(self.env, tkt_id)
            tkt_group = self._get_ticket_group(linked_ticket.tkt)
            append_ticket(linked_ticket, tkt_group, linked_ticket.tkt['milestone'])
            
        for mil in milestone:
            if not user_stories.has_key(mil):
                user_stories[mil] = {'fields':milestone_sum_fields}
        data['stories'] = user_stories
        
    def _resolve_milestone(self, name):
        if name=='nearest':
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute('SELECT name FROM milestone WHERE due>%s ORDER BY due LIMIT 1', (to_timestamp(datetime.now(utc)),))
            row = cursor.fetchone()
            name=row and row[0] or 'none'
        elif name=='not_completed_milestones':
            return [mil.name for mil in Milestone.select(self.env, False)]        
        if name=='none':
            return ''        
        return StructuredMilestone(self.env, name).name
        
            
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
    
    def _get_ticket_ids(self, milestone=None, eq=False, userfilter= None):
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        sql_params = [milestone, self.user_story_ticket_type]
        
        sql = 'SELECT id FROM ticket WHERE (milestone'
        if milestone=='' or isinstance(milestone, list) and '' in milestone:
            sql += ' IS NULL or milestone'
        if isinstance(milestone, list):
            sql += " IN (%s)" % ("%s,"*len(milestone))[:-1]
            sql_params[0:1] = milestone
        else:
            sql+='=%s'
        sql+=') and type%s%%s' % (eq and '=' or '<>')        

        if userfilter:
            sql += ' AND owner=%s' 
            sql_params.append(userfilter)
        cursor.execute(sql, tuple(sql_params))
        ids = [int(tkt_id) for tkt_id, in cursor]       
        return ids
        
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

    def _add_rendering_properties(self, ticket, field_name, max_weight, props):
        tkt_cfg = self.ticket_type_config
        if tkt_cfg:
            cfg = tkt_cfg.get(ticket.tkt['type'])
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