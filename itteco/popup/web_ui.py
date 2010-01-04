import pkg_resources
from datetime import datetime, timedelta

from genshi.builder import tag

from trac.core import Component, implements, TracError
from trac.resource import Resource, ResourceNotFound
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket, Resolution, Type
from trac.util.datefmt import utc, to_datetime
from trac.util.translation import _
from trac.web.api import IRequestHandler
from trac.web.chrome import ITemplateProvider, add_script, add_stylesheet

from itteco.init import IttecoEvnSetup
from itteco.calendar.model import Calendar, CalendarType, Event, TimeTrack
from itteco.calendar.util import cal_as_dict, event_as_dict
from itteco.ticket.model import StructuredMilestone
from itteco.scrum.web_ui import DashboardModule

class PopupModule(Component):
    implements(IRequestHandler, ITemplateProvider)
    
    # IRequestHandler methods
    def match_request(self, req):           
        if req.path_info.startswith('/popup'):
            path = req.path_info.split('/') 
            if len(path)>1:
                req.args['area'] = path[2]
                req.args['obj_id'] = len(path)>3 and path[3] or None
                return True
        return False
           

    def process_request(self, req):        
        area = req.args['area']
        method = getattr(self, area, None)
        if method is None:
            raise TracError(_('Popup are %(area)s not found.', area = area))
        return method(req)
        
    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        return []

    def get_templates_dirs(self):
        return [pkg_resources.resource_filename('itteco.popup', 'templates')]
    
    # popup implementors
    def events(self, req):
        user = req.authname
        event_id = req.args.get('obj_id') or None
        event = Event(self.env, event_id)
        cal_id = event_id and event.calendar or req.args.get('calendar')
        if not event_id:
            event.calendar = cal_id
            event.allday = req.args.get('allDay')=='true' and 1 or 0;
            getdate= lambda x: to_datetime(long(req.args[x]), utc)
            event.dtstart = getdate('date')
            event.dtend = event.dtstart + timedelta(minutes=30)
        else:
            tt = TimeTrack(self.env, event.id, user)
            event.time_track = tt
        data = {
            'event'     : event and event_as_dict(event) or None,
            'tickets'   : self._get_active_tickets(user),
            'calendars' : 
                [cal_as_dict(cal, user) for cal in Calendar.select(self.env, owner=user)
                    if cal.type!=CalendarType.Reference]
        }
        return 'itteco_event_form.html', data, None
    
    def _get_active_tickets(self, user):
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

    def tickets(self, req):
        tkt_id = req.args.get('obj_id')
        if tkt_id:        
            req.perm.require('TICKET_MODIFY', Resource('ticket', tkt_id))
        else:
            req.perm.require('TICKET_CREATE')
        
        descriptor = DashboardModule(self.env).get_new_ticket_descriptor(
                [ type.name for type in Type.select(self.env)],
                tkt_id
        )
        
        data = {
            'structured_milestones' : StructuredMilestone.select(self.env),
            'resolutions' : [],#val.name for val in Resolution.select(self.env)],
            'new_ticket_descriptor' : descriptor,
            'action_controls' : self._get_action_controls(req, descriptor['ticket'])
        }
        return 'itteco_ticket_edit.html', data, 'text/html'
        
    def _get_action_controllers(self, req, ticket, action):
        """Generator yielding the controllers handling the given `action`"""
        for controller in TicketSystem(self.env).action_controllers:
            actions = [a for w,a in
                       controller.get_ticket_actions(req, ticket)]
            if action in actions:
                yield controller

    def _get_action_controls(self, req, ticket):
        action_controls = []
        sorted_actions = TicketSystem(self.env).get_available_actions(req,
                                                                      ticket)
        for action in sorted_actions:
            first_label = None
            hints = []
            widgets = []
            for controller in self._get_action_controllers(req, ticket,
                                                           action):
                label, widget, hint = controller.render_ticket_action_control(
                    req, ticket, action)
                if not first_label:
                    first_label = label
                widgets.append(widget)
                hints.append(hint)
            action_controls.append((action, first_label, tag(widgets), hints))
        return action_controls

    def comment(self, req):
        tkt_id = req.args.get('obj_id')
        if tkt_id:        
            req.perm.require('TICKET_MODIFY', Resource('ticket', tkt_id))
            
        tkt = Ticket(self.env, tkt_id)
        if not tkt.exists:
            raise ResourceNotFound('Ticket %s does not exist.' % tkt_id,
                                   'Invalid Ticket Id')
        return 'itteco_ticket_comment.html', {'ticket': tkt}, 'text/html'
