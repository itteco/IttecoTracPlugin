import re

from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import Component, implements
from trac.search.web_ui import SearchModule
from trac.ticket import Ticket, Type
from trac.ticket.web_ui import TicketModule
from trac.util.translation import _
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import Chrome, add_stylesheet, add_script, add_ctxtnav
from trac.wiki.web_ui import WikiModule

from itteco.ticket.admin import IttecoMilestoneAdminPanel
from itteco.ticket.model import TicketLinks, StructuredMilestone
from itteco.utils.json import write
from itteco.utils.render import hidden_items

class IttecoTicketModule(Component):
    implements(ITemplateStreamFilter, IRequestFilter)
    
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
            links = TicketLinks(self.env, ticket)
            links.outgoing_links = [int(id) for id in req.args.get('links_ticket', [])]
            wiki_ids = req.args.get('links_wiki', [])
            wiki_ids = not isinstance(wiki_ids, list) and (wiki_ids,) or wiki_ids
            links.wiki_links = wiki_ids
            links.save()
        return req.args['original_handler'].process_request(req)
                
    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/ticket/') or req.path_info.startswith('/newticket') or req.path_info.startswith('/milestone'):
            add_stylesheet(req, 'itteco/css/common.css')
            add_script(req, 'itteco/js/custom_select.js')
        if req.path_info.startswith('/ticket/'):
            add_script(req, 'itteco/js/jquery.ui/ui.core.js')
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
            mydata ={'milestones':StructuredMilestone.select(self.env),
                  'max_level':  levels and len(levels)-1 or 0,
                  'milestone_name' : milestone and milestone.parent or None,
                  'field_name' : 'parent'}
            stream |=Transformer('//*[@id="target"]').after(chrome.render_template(req, 'itteco_milestones_dd.html', mydata, fragment=True))
            
        if 'ticket' in data:
            mydata ={'milestones':StructuredMilestone.select(self.env),
                 'milestone_name': data['ticket']['milestone'],
                 'field_name' : 'field_milestone'}
            req.chrome.setdefault('ctxtnav',[]).insert(-1, tag.a(_('Open Containing Whiteboard'), href=req.href.whiteboard('team_tasks',data['ticket']['milestone'] or 'none')))
            stream |=Transformer('//*[@id="field-milestone"]').replace(chrome.render_template(req, 'itteco_milestones_dd.html', mydata, fragment=True))

        if 'ticket_links' in data:
            mydata = dict()
            mydata['in_links'] = {'title':'Referred by:', 'blockid':'inblock', 'removable': False, 'links': self._ids_to_tickets(data['ticket_links'].incoming_links)}
            mydata['out_links'] = {'title':'Refers to:', 'blockid':'outblock', 'removable': True, 'links': self._ids_to_tickets(data['ticket_links'].outgoing_links)}
            mydata['wiki_links']= data['ticket_links'].wiki_links
            mydata['filters']=data.get('filters',[])
            stream |=Transformer('//*[@id="ticket"]').append(chrome.render_template(req, 'itteco_links.html', mydata, fragment=True))
            stream |=Transformer('//*[@id="content"]').after(chrome.render_template(req, 'itteco_search_pane.html', mydata, fragment=True));
            stream |=Transformer('//*[@id="propertyform"]').append(hidden_items('links_ticket', data['ticket_links'].outgoing_links))
            stream |=Transformer('//*[@id="propertyform"]').append(hidden_items('links_wiki', data['ticket_links'].wiki_links))
        return stream
        
    def _ids_to_tickets(self, ids):
        all_types = [ticket.name for ticket in Type.select(self.env)]
        tickets = list()
        for tkt_id in ids:
            ticket = Ticket(self.env, tkt_id)
            ticket['idx'] ='%02d' % all_types.index(ticket['type']) 
            tickets.append(ticket)
        tickets.sort(key= lambda x: '%s %s' % (x['idx'], x.id))
        return tickets

    def get_ticket_search_results(self, req):
        req.args['ticket']=1
        template, data, arg = SearchModule(self.env).process_request(req)
        return data
        
    def _get_search_filters(self, req):
        filters = []
        if TicketModule(self.env).get_search_filters(req) is not None:
            filters += [{'name': ticket.name, 'label':ticket.name, 'active': True } for ticket in Type.select(self.env)]
        wikifilters = WikiModule(self.env).get_search_filters(req)
        if wikifilters:
            filters += [{'name': f[0], 'label':f[1], 'active': True } for f in wikifilters]
        return filters

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
                    res['title']='%s %s:%s' % (ticket_type, match.group(1), match.group(3))
                    res['idx'] = '%02d' % all_types.index(ticket_type)
            else:
                res['title'] = 'wiki: %s' % res['title'].split(':',2)[0]
                res['idx']=99
            filtered_res.append(res)
        
        filtered_res.sort(key= lambda x: '%s %s' % (x['idx'], x['title']))
        json_val = write(filtered_res)
        req.write('({"items":'+json_val+'})')