import re

from datetime import datetime

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements
from trac.resource import Resource
from trac.ticket import Ticket, Type
from trac.ticket.web_ui import TicketModule
from trac.timeline.api import ITimelineEventProvider
from trac.util.datefmt import to_timestamp, utc
from trac.util.translation import _
from trac.util.text import to_unicode
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import Chrome, add_stylesheet, add_ctxtnav
from trac.wiki.web_ui import WikiModule

from itteco.init import IttecoEvnSetup
from itteco.ticket.admin import IttecoMilestoneAdminPanel
from itteco.ticket.model import TicketLinks, StructuredMilestone
from itteco.ticket.utils import get_fields_by_names, get_tickets_by_ids
from itteco.utils.json import write
from itteco.utils.render import hidden_items, add_jscript

class RedirectInterceptor(object):
    def __init__(self, req, mapper):
        self.req = req
        self.mapper = mapper
        
    def redirect(self, url):
        req = object.__getattribute__(self, 'req')
        mapper = object.__getattribute__(self, 'mapper')
        req.redirect(mapper(req, url))
        
    def __getattribute__(self, name):
        if name=='redirect':
            return object.__getattribute__(self, name)
            
        return getattr(object.__getattribute__(self, 'req'), name)

class IttecoTicketModule(Component):
    implements(ITemplateStreamFilter, ITimelineEventProvider, IRequestFilter)
    
    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        if req.path_info.startswith('/ticket/'):
            req.args['original_handler']=handler
            return self
        return handler

    def process_request(self, req):
        if req.method=='POST' and ('preview' not in req.args):
            id = int(req.args.get('id'))
            ticket = Ticket(self.env, id)
            if ticket.exists:
                def get_ids(req, attr_name):
                    ids = req.args.get(attr_name, [])
                    return isinstance(ids, basestring) and (ids,) or ids
                    
                links = TicketLinks(self.env, ticket)
                links.outgoing_links = [int(id) for id in get_ids(req, 'ticket_links')]
                links.wiki_links = get_ids(req, 'wiki_links')
                links.save()
        template, data, content_type = req.args['original_handler'].process_request(RedirectInterceptor(req, self._get_jump_to_url))
        if template == 'ticket.html':
            add_jscript(
                req, 
                [
                    'stuff/plugins/jquery.rpc.js',
                    'references.js'
                ],
                IttecoEvnSetup(self.env).debug
            )
            tkt = data['ticket']
            links = TicketLinks(self.env, tkt)
            data['filters']=self._get_search_filters(req)
            data['ticket_links'] = {
                'incoming' : {
                    'title':'Referred by:',
                    'blockid':'inblock', 
                    'removable': False, 
                    'links': self._ids_to_tickets(links.incoming_links)
                },
                'outgoing' : {
                    'title':'Refers to:', 
                    'blockid':'outblock', 
                    'removable': True, 
                    'links': self._ids_to_tickets(links.outgoing_links)
                },
                'wiki' : links.wiki_links
            }
            
            return 'itteco_ticket.html', data, content_type
        return template, data, content_type
    
    def post_process_request(self, req, template, data, content_type):
        self.env.log.debug('post_process_request req=%s, pathinfo=%s, args=%s' % (req, req.path_info, req.args))
        if req.path_info.startswith('/ticket/') \
            or req.path_info.startswith('/newticket') \
            or req.path_info.startswith('/milestone') \
            or req.path_info.startswith('/roadmap'):
            
            add_stylesheet(req, 'itteco/css/common.css')
            add_jscript(
                req, 
                [
                    'stuff/ui/ui.core.js',
                    'stuff/ui/ui.resizable.js',
                    'stuff/ui/ui.draggable.js',
                    'stuff/ui/ui.droppable.js',
                    'custom_select.js'
                ],
                IttecoEvnSetup(self.env).debug
            )

        return template, data, content_type
        
    def _get_jump_to_url(self, req, original_url):
        jump_target = req.args.get('jump_to')
        
        if 'original_handler' not in req.args or jump_target is None or jump_target=='stay':
            return original_url
        
        if jump_target=='reports' and req.session.get('query_href'):
            return req.session.get('query_href')
            
        if jump_target=='whiteboard':
            return req.href.whiteboard('team_tasks')+'#'+req.args.get('field_milestone', '')
        return original_url
    
    def filter_stream(self, req, method, filename, stream, data):
        chrome = Chrome(self.env)

        if req.path_info.startswith('/milestone') \
            and req.args.get('action') in ['edit', 'new'] \
            and 'max_level' not in data:
            milestone = data.get('milestone')
            levels = IttecoMilestoneAdminPanel(self.env).milestone_levels
            mydata ={'structured_milestones':StructuredMilestone.select(self.env),
                  'max_level':  levels and len(levels)-1 or 0,
                  'milestone_name' : milestone and milestone.parent or None,
                  'field_name' : 'parent'}
            stream |=Transformer('//*[@id="edit"]/fieldset').append(
                chrome.render_template(req, 'itteco_milestones_dd.html', mydata, fragment=True))
            
        if 'ticket' in data:
            tkt = data['ticket']
            mydata ={
                'structured_milestones':StructuredMilestone.select(self.env),
                'milestone_name': data['ticket']['milestone'],
                'field_name' : 'field_milestone',
                'hide_completed' : not ( tkt.exists and 'TICKET_ADMIN' in req.perm(tkt.resource))
            }
            req.chrome.setdefault('ctxtnav',[]).insert(
                -1, 
                tag.a(
                    _('Go To Whiteboard'), 
                    href=req.href.whiteboard('team_tasks', data['ticket']['milestone'] or 'none')
                )
            )
            stream |=Transformer('//*[@id="field-milestone"]').replace(
                chrome.render_template(req, 'itteco_milestones_dd.html', mydata, fragment=True))
        return stream
        
    def _ids_to_tickets(self, ids):
        if ids:
            all_types = [type.name for type in Type.select(self.env)]
            fields = get_fields_by_names(self.env, 'summary')
            tickets = []
            for tkt_info in get_tickets_by_ids(self.env.get_db_cnx(), fields, ids):
                tkt_info['idx'] ='%02d' % all_types.index(tkt_info['type'])
                tickets.append(tkt_info)
            tickets.sort(key= lambda x: '%s %s' % (x['idx'], x['id']))
            return tickets
        return []

    def get_ticket_search_results(self, req):
        req.args['ticket']=1
        template, data, arg = SearchModule(self.env).process_request(req)
        return data
        
    def _get_search_filters(self, req):
        filters = []
        if TicketModule(self.env).get_search_filters(req) is not None:
            filters.extend(
                [
                    {
                        'name': ticket.name, 
                        'label':ticket.name, 
                        'active': True
                    }
                    for ticket in Type.select(self.env)
                ]
            )
        wikifilters = WikiModule(self.env).get_search_filters(req)
        if wikifilters:
            filters.extend(
                [
                    {
                        'name': f[0], 
                        'label':f[1], 
                        'active': True
                    }
                    for f in wikifilters
                ]
            )
        return filters
        
    # ITimelineEventProvider methods
    def get_timeline_filters(self, req):
        if 'TICKET_VIEW' in req.perm and not TicketModule(self.env).timeline_details:
            yield ('ticket_comments', _('Commented tickets'))

    def get_timeline_events(self, req, start, stop, filters):
        ticket_realm = Resource('ticket')

        # Ticket comments
        if 'ticket_comments' in filters:
            event_renderer = TicketModule(self.env)
            
            def produce_event((id, ts, author, type, summary, description),
                              comment, cid):
                ticket = ticket_realm(id=id)
                if 'TICKET_VIEW' not in req.perm(ticket):
                    return None
                return ('commentedticket', datetime.fromtimestamp(ts, utc), author,
                        (ticket, 'commented', '', summary, 'edit', None, type,
                         description, comment, cid), event_renderer)

            ts_start = to_timestamp(start)
            ts_stop = to_timestamp(stop)
                         
            db = self.env.get_db_cnx()
            cursor = db.cursor()

            cursor.execute("SELECT t.id,tc.time,tc.author,t.type,t.summary, "
                           "       tc.field,tc.oldvalue,tc.newvalue "
                           "  FROM ticket_change tc "
                           "    INNER JOIN ticket t ON t.id = tc.ticket "
                           "      AND tc.time>=%s AND tc.time<=%s "
                           "      AND tc.field='comment' "
                           "      AND tc.newvalue IS NOT NULL "
                           "      AND tc.newvalue<>'' "
                           "ORDER BY tc.time"
                           % (ts_start, ts_stop))
            for id,t,author,type,summary,field,oldvalue,comment in cursor:
                cid = oldvalue and oldvalue.split('.')[-1]
                ev = produce_event((id, t, author, type, summary, None), 
                                   comment, cid)
                if ev:
                    yield ev
                    
    def render_timeline_event(self, context, field, event):
        pass#we are delegating rendering to standard trac TicketModule