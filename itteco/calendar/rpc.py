from datetime import datetime
import re

from trac.core import *
from trac.attachment import Attachment
from trac.resource import Resource
from trac.search.api import ISearchSource
from trac.search.web_ui import SearchModule
from trac.ticket.web_ui import TicketModule
from trac.ticket.model import Ticket, Type
from trac.util.datefmt import FixedOffset, format_datetime, parse_date, utc, to_timestamp
from trac.util.text import to_unicode

from tracrpc.api import IXMLRPCHandler

from itteco.init import IttecoEvnSetup
from itteco.calendar.model import Calendar, Event, TimeTrack
from itteco.calendar.util import *
from itteco.ticket.model import TicketLinks


class CalendarRPC(Component):
    """ An interface to Calendar sub-sustem. """

    implements(IXMLRPCHandler)
    
    calendar_realm = Resource('calendar')

    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'calendar'

    def xmlrpc_methods(self):
        yield (None, ((list,), (list, str)), self.query)
        yield (None, 
            (
                (dict, int, str, int), \
                (dict, int, str, int, str), \
                (dict, int, str, int, str, int)
            ), self.save)
        yield (None, ((dict, int),), self.remove)

    # Exported methods
    def query(self, req):
        """ Returns list of available Calendars. """
        username = req.authname
        out = []
        for c in Calendar.select(self.env):
            if 'CALENDAR_VIEW' in req.perm(c.resource):
                out.append(cal_as_dict(c, username))
        return out
        
    def save(self, req, id, name, theme, type, ref=0):
        """ Creates or saves a calendar. """
        username = req.authname
        
        id = id or None
        if not id:
            req.perm.require('CALENDAR_CREATE')
        else:
            req.perm.require('CALENDAR_MODIFY', self.calendar_realm(id=id))
            
        c = Calendar(self.env, id)
        c.name = name
        c.theme = theme
        c.type = type
        c.ref = ref
        if id and c.exists:
            c.update()
        else:
            c.owner = username
            c.insert()            
        return cal_as_dict(c, username)
   
    def remove(self, req, id):
        """ Deleted the given calendar"""
        username = req.authname
        req.perm.require('CALENDAR_DELETE', self.calendar_realm(id=id))
        c = Calendar(self.env, id)
        c.delete()
        return cal_as_dict(c, username)
        
class EventRPC(Component):
    """ An interface to Calendar Events. """

    implements(IXMLRPCHandler)
    
    calendar_realm = Resource('calendar')
    
    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'event'

    def xmlrpc_methods(self):
        yield (None, ((list, int, int, int),), self.query)
        yield (None, 
            (
                (dict, str, int, str, str, int, int, str, int, str, str, str, int), 
            ), self.save)
        yield (None, ((dict, int),), self.delete)

    # Exported methods
    def query(self, req, start, end, tzoffset):
        username =  req.authname
        tz = FixedOffset(tzoffset, 'Browser offset')
        events = [
            event_as_dict(event)
            for event in Event.select(self.env, username, daterange=[start, end])
        ]
        
        return events
    
    def save(self, req, id, calendar, name, allday, start, end, description, ticket, timetrack, auto, time, tzoffset=None):
        username =  req.authname
        id = id and str(id) or None
        tz = tzoffset and FixedOffset(-1*int(tzoffset), 'Browser offset') or utc
        c = Calendar(self.env, calendar)
        req.perm.require('CALENDAR_VIEW', c.resource)
        e = self.save_event(req, id, c, name, allday, start, end, description, ticket, tz)
        self.save_timetrack(req, e, timetrack, auto, time)
        self.env.log.debug('tt %s' % (e.time_track))
        return event_as_dict(e)
        
    def delete(self, req, id):
        pass
        
    def save_event(self, req, id, calendar, name, allday, start, end, description, ticket, tz):
        e = Event(self.env, id)
        self.env.log.debug('cal-res=%s, id=%s' % (calendar.resource, calendar.resource.id))
        if calendar.exists and 'CALENDAR_MODIFY' in req.perm(calendar.resource):
            e.title = name
            e.description = description
            e.calendar = calendar.id
            e.ticket = ticket or 0
            e.dtstart = parse_datetime(start, tz)
            e.dtend = parse_datetime(end,tz)
            e.allday = bool_to_int(allday)
            
            if e.exists:
                e.update()
            else:
                e.insert()
        return e
        
    def save_timetrack(self, req, event, timetrack, auto, time):
        tt = TimeTrack(self.env, event.id, req.authname)
        
        if bool_to_int(timetrack):
            auto = bool_to_int(auto)
            if auto:
                time = 0
            else:
                time = time_in_minutes(time)
            
            tt.auto = auto
            tt.time = time
            if tt.exists:
                tt.update()
            else:
                tt.insert()
            event.time_track = tt
        elif tt.exists:
            tt.delete()
            event.time_track=None

    
class TicketConfigRPC(Component):
    """ An interface for ticket fields configuration. """

    implements(IXMLRPCHandler)

    search_sources = ExtensionPoint(ISearchSource)

    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'ticketconfig'

    def xmlrpc_methods(self):
        yield (None, ((dict,),), self.defaults)
        yield (None, ((dict, int, int), (dict, int, int, int)), self.trace)
        yield (None, ((list,),),  self.my_active_tickets)
        yield (None, ((list, str),(list, str, list),),  self.references_search)
        yield (None, ((dict, list, str),),  self.apply_preset)

    def defaults(self, req):
        """ Returns dictionary of the default field values"""
        t = Ticket(self.env)
        return t.values
        
    def trace(self, req, source, target, old_target = None):
        """ Make tickets traceble. The direction is from source to target."""
        tkt_link = TicketLinks(self.env, source)
        if old_target:
            tkt_link.outgoing_links.remove(int(old_target))
        if target:
            tkt_link.outgoing_links.add(target)
        tkt_link.save()
        return {'source' : source, 'target': target}
        
    def my_active_tickets(self, req):
        """ Returns all none closed tickets assigned to the current user."""
        user = req.authname
        def ticket_as_dict(id, summary):
            return {
                'ticketId': id, 
                'summary': summary
            }
            
        final_statuses = [status for status in IttecoEvnSetup(self.env).final_statuses]

        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute("""
            SELECT id as ticketId, summary
              FROM ticket
             WHERE owner = %%s AND status NOT IN (%s)""" % ("%s," * len(final_statuses))[:-1],
           [user,]+final_statuses)
        return [ticket_as_dict(tktId, summary) for tktId, summary in cursor]
        
    def references_search(self, req, q, filters=[]):
        """ Returns list of possible references objects for given search parameters."""
        if not q or not filters:
            return []
        query = SearchModule(self.env)._get_search_terms(q)

        all_types = [ticket.name for ticket in Type.select(self.env)]       
        used_types = [t for t in all_types if filters]
        if used_types:
            filters.append('ticket')
        filtered_res =[]
        for source in self.search_sources:
            for href, title, date, author, excerpt in source.get_search_results(req, query, filters):
                self.env.log.debug('references_search-res=%s' % ((href, title, date, author, excerpt),))
                path = href.split('/')
                res = {
                    'href': href,
                    'date': date,
                    'author': author,
                    'excerpt': excerpt,
                    'title' : title,
                    'type': path[-2],
                    'id': path[-1]
                }
                if(res['type']=='ticket'):
                    #hack to avoid database access
                    self.env.log.debug('references_search-ticket=%s' % res)

                    match = re.match('<span .+?>(.*?)</span>:(.+?):(.*)', str(title))
                    if match:
                        ticket_type = match.group(2).strip()
                        self.env.log.debug('references_search-ticket-type=%s' % ticket_type)
                        if ticket_type not in filters:
                            continue
                        res.update(
                            {
                                'title' :to_unicode(match.group(3)),
                                'idx': '%02d' % all_types.index(ticket_type),
                                'subtype' : ticket_type
                            }
                        )
                else:
                    res['title'] = to_unicode('wiki: %s' % res['title'].split(':',2)[0])
                    res['idx']=99
                filtered_res.append(res)
        
        filtered_res.sort(key= lambda x: '%s %s' % (x['idx'], x['title']))
        return filtered_res
    def apply_preset(self, req, tickets, preset=None):
        if preset is None:
            return tickets
            
        presets = preset and [kw.split('=', 1) for kw in preset.split('&')] or []
        fields = dict([(field, value) for field, value in presets])

        warn = []
        modified_tickets = []
        if tickets and presets:
            db = self.env.get_db_cnx()
            ticket_module = TicketModule(self.env)
            action = fields.get('action')

            for ticket_id in tickets:
                if 'TICKET_CHGPROP' in req.perm('ticket', ticket_id):
                    ticket  = Ticket(self.env, ticket_id, db)
                    ticket.populate(fields)
                    if action:
                        field_changes, problems = ticket_module.get_ticket_changes(req, ticket, action)
                        if problems:
                            for problem in problems:
                                warn.append(problem)
                        ticket_module._apply_ticket_changes(ticket, field_changes) # Apply changes made by the workflow

                    ticket.save_changes(req.authname, None, db=db)
                    modified_tickets.append(ticket_id)
                else:
                    warn.append(_("You have no permission to modify ticket '%(ticket)s'", ticket=ticket_id))
            db.commit()
        return { 'tickets' : modified_tickets, 'warnings': warn}
        
class AttachmentRPC(Component):
    """ An interface for attachments manipulations. """

    implements(IXMLRPCHandler)

    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'attachment'

    def xmlrpc_methods(self):
        yield (None, ((bool, str, str, str),), self.remove)
        
    def remove(self, req, realm, objid, filename):
        """ Delete an attachment. """
        resource = Resource(realm, objid).child('attachment', filename)
        attachment = Attachment(self.env, resource)
        req.perm(attachment.resource).require('ATTACHMENT_DELETE')
        attachment.delete()
        return True

