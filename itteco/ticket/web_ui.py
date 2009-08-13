import re

from datetime import datetime

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements
from trac.resource import Resource
from trac.ticket import Ticket, Type
from trac.ticket.web_ui import TicketModule
from trac.timeline.api import ITimelineEventProvider
from trac.search.web_ui import SearchModule
from trac.util.datefmt import to_timestamp, utc
from trac.util.translation import _
from trac.util.text import to_unicode
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import Chrome, add_stylesheet, add_script, add_ctxtnav
from trac.wiki.web_ui import WikiModule

from itteco.ticket.admin import IttecoMilestoneAdminPanel
from itteco.ticket.model import TicketLinks, StructuredMilestone
from itteco.ticket.utils import get_fields_by_names, get_tickets_by_ids
from itteco.utils.json import write
from itteco.utils.render import hidden_items

class IttecoTicketModule(Component):
    implements(ITemplateStreamFilter, ITimelineEventProvider, IRequestFilter)
    
    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        if req.path_info.startswith('/ticket/') and req.method=='POST' and ('preview' not in req.args):
            req.args['original_handler']=handler
            return self
        return handler

    def process_request(self, req):
        id = int(req.args.get('id'))
        ticket = Ticket(self.env, id)
        if ticket.exists:
            def get_ids(req, attr_name):
                ids = req.args.get(attr_name, [])
                return isinstance(ids, basestring) and (ids,) or ids
                
            links = TicketLinks(self.env, ticket)
            links.outgoing_links = [int(id) for id in get_ids(req, 'links_ticket')]
            links.wiki_links = get_ids(req, 'links_wiki')
            links.save()
        return req.args['original_handler'].process_request(req)
                    
    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/ticket/') \
            or req.path_info.startswith('/newticket') \
            or req.path_info.startswith('/milestone'):
            
            add_stylesheet(req, 'itteco/css/common.css')
            add_script(req, 'itteco/js/jquery.ui/ui.core.js')
            add_script(req, 'itteco/js/jquery.ui/ui.resizable.js')
            add_script(req, 'itteco/js/custom_select.js')
        if req.path_info.startswith('/ticket/'):
            add_script(req, 'itteco/js/jquery.ui/ui.draggable.js')
            add_script(req, 'itteco/js/jquery.ui/ui.droppable.js')
            add_script(req, 'itteco/js/dndsupport.js')
            tkt = data['ticket']
            links = TicketLinks(self.env, tkt)
            data['filters']=self._get_search_filters(req)
            data['ticket_links'] = links            
        return template, data, content_type
    
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
            mydata ={'structured_milestones':StructuredMilestone.select(self.env),
                 'milestone_name': data['ticket']['milestone'],
                 'field_name' : 'field_milestone',
                 'hide_completed' : not ( tkt.exists and 'TICKET_ADMIN' in req.perm(tkt.resource))
                 }
            req.chrome.setdefault('ctxtnav',[]).insert(
                -1, tag.a(
                    _('Open Containing Whiteboard'), 
                    href=req.href.whiteboard('team_tasks', data['ticket']['milestone'] or 'none')))
            stream |=Transformer('//*[@id="field-milestone"]').replace(
                chrome.render_template(req, 'itteco_milestones_dd.html', mydata, fragment=True))

        if 'ticket_links' in data:
            mydata = dict()
            mydata['in_links'] = {'title':'Referred by:', 'blockid':'inblock', 
                'removable': False, 'links': self._ids_to_tickets(data['ticket_links'].incoming_links)}
            mydata['out_links'] = {'title':'Refers to:', 'blockid':'outblock', 
                'removable': True, 'links': self._ids_to_tickets(data['ticket_links'].outgoing_links)}
            mydata['wiki_links']= data['ticket_links'].wiki_links
            mydata['filters']=data.get('filters',[])
            stream |=Transformer('//*[@id="ticket"]').append(
                chrome.render_template(req, 'itteco_links.html', mydata, fragment=True))
            stream |=Transformer('//*[@id="content"]').after(
                chrome.render_template(req, 'itteco_search_pane.html', mydata, fragment=True));
            stream |= Transformer('//*[@id="propertyform"]').append( \
                tag(hidden_items('links_ticket', data['ticket_links'].outgoing_links), \
                    hidden_items('links_wiki', data['ticket_links'].wiki_links)))
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

    def get_ticket_search_results(self, req):
        req.args['ticket']=1
        template, data, arg = SearchModule(self.env).process_request(req)
        return data
        
    def _get_search_filters(self, req):
        filters = []
        if TicketModule(self.env).get_search_filters(req) is not None:
            filters += [{'name': ticket.name, 'label':ticket.name, 'active': True } 
                for ticket in Type.select(self.env)]
        wikifilters = WikiModule(self.env).get_search_filters(req)
        if wikifilters:
            filters += [{'name': f[0], 'label':f[1], 'active': True } for f in wikifilters]
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

class JSonSearchtModule(Component):
    implements(IRequestHandler)

    def match_request(self, req):
        return req.path_info.startswith('/jsonsearch')

    def process_request(self, req):
        all_types = [ticket.name for ticket in Type.select(self.env)]       
        types = [t for t in all_types if req.args.has_key(t)]
        if types:
            req.args['ticket']=1
        template, data, arg = SearchModule(self.env).process_request(req)
        results = [ res for res in data['results']]
        filtered_res =[]
        for res in results:
            res['type']=res['href'].split('/')[-2]
            if(res['type']=='ticket'):
                #hack to avoid database access
                match = re.match('<span .+?>(.*?)</span>:(.+?):(.*)', str(res['title']))
                if match:
                    ticket_type = match.group(2).strip()
                    if not req.args.has_key(ticket_type):
                        continue
                    res['title']=to_unicode('%s %s:%s' % (ticket_type, match.group(1), match.group(3)))
                    res['idx'] = '%02d' % all_types.index(ticket_type)
            else:
                res['title'] = to_unicode('wiki: %s' % res['title'].split(':',2)[0])
                res['idx']=99
            filtered_res.append(res)
        
        filtered_res.sort(key= lambda x: '%s %s' % (x['idx'], x['title']))
        json_val = write(filtered_res)
        req.write('({"items":'+json_val+'})')