from datetime import datetime

from trac.core import Component, implements
from trac.resource import Resource
from trac.ticket.model import Ticket
from trac.util.datefmt import FixedOffset, format_datetime, parse_date, utc, to_timestamp

from tracrpc.api import IXMLRPCHandler

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
        yield (None, ((dict, int),), self.delete)

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
   
    def delete(self, req, id):
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
        id = id or None
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

    # IXMLRPCHandler methods
    def xmlrpc_namespace(self):
        return 'ticketconfig'

    def xmlrpc_methods(self):
        yield (None, ((dict,),), self.defaults)
        yield (None, ((dict, int, int), (dict, int, int, int)), self.trace)

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
