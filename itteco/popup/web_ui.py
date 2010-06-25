import pkg_resources
from datetime import datetime, timedelta

from genshi.builder import tag

from trac.attachment import Attachment
from trac.core import Component, implements, TracError
from trac.resource import Resource, ResourceNotFound
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket, Resolution, Type
from trac.ticket.web_ui import TicketModule
from trac.util import get_reporter_id
from trac.util.datefmt import utc, to_datetime
from trac.util.translation import _
from trac.web.api import IRequestHandler
from trac.web.chrome import ITemplateProvider

from itteco.init import IttecoEvnSetup
from itteco.calendar.model import Calendar, CalendarType, Event, TimeTrack
from itteco.calendar.rpc import TicketConfigRPC
from itteco.calendar.util import cal_as_dict, event_as_dict
from itteco.ticket.model import StructuredMilestone
from itteco.scrum.web_ui import WhiteboardModule
from itteco.utils.json import write

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
    
    def calendars(self, req):
        cal_id = req.args.get('obj_id')
        if cal_id:        
            req.perm.require('CALENDAR_MODIFY', Resource('calendar', cal_id))
            cal = Calendar(self.env, cal_id)
        else:
            req.perm.require('CALENDAR_CREATE')
            cal = Calendar(self.env)
                
        data = {
            'calendar' : cal
        }
        return 'itteco_calendar_edit.html', data, 'text/html'
        
    def events(self, req):
        user = req.authname
        event_id = req.args.get('obj_id') or None
        event = Event(self.env, event_id)
        cal_id = event_id and event.calendar or req.args.get('calendar')
        own = True
        if not event_id:
            event.calendar = cal_id
            event.allday = req.args.get('allDay')=='true' and 1 or 0
            ticket = req.args.get('ticket')
            ticket = ticket and Ticket(self.env, int(ticket)) or None
            if ticket and ticket.exists and 'TICKET_VIEW' in req.perm(ticket.resource):
                event.ticket = ticket.id
                event.title = ticket['summary']
                event.time_track = TimeTrack(self.env)
            getdate= lambda x: to_datetime(long(req.args[x]), utc)
            event.dtstart = getdate('date')
            event.dtend = event.dtstart + timedelta(minutes=60)
        else:
            cal = Calendar(self.env, event.calendar)
            own = cal.owner==user
            tt = TimeTrack(self.env, event.id, user)
            event.time_track = tt
        data = {
            'event'     : event and event_as_dict(event, own) or None,
            'tickets'   : TicketConfigRPC(self.env).my_active_tickets(req),
            'calendars' : 
                [cal_as_dict(cal, user) for cal in Calendar.select(self.env, owner=user)
                    if cal.type!=CalendarType.Reference]
        }
        return 'itteco_event_form.html', data, None
    
    def ticket(self, req):
        tkt_id = req.args.get('obj_id')
        if tkt_id:        
            req.perm.require('TICKET_MODIFY', Resource('ticket', tkt_id))
        else:
            req.perm.require('TICKET_CREATE')
        
        descriptor = WhiteboardModule(self.env).get_new_ticket_descriptor(
                [ type.name for type in Type.select(self.env)],
                tkt_id
        )
        
        data = {
            'structured_milestones' : StructuredMilestone.select(self.env),
            'resolutions' : [],#val.name for val in Resolution.select(self.env)],
            'new_ticket_descriptor' : descriptor,
            'action_controls' : self._get_action_controls(req, descriptor['ticket']),
        }
        return 'itteco_ticket_edit.html', data, 'text/html'

    def milestone(self, req):
        mil_id = req.args.get('obj_id')
        if mil_id:        
            req.perm.require('MILESTONE_MODIFY', Resource('milestone', mil_id))
        else:
            req.perm.require('MILESTONE_CREATE')
        
        milestone = StructuredMilestone(self.env, mil_id)
        descriptor = WhiteboardModule(self.env).get_new_ticket_descriptor(
                [ type.name for type in Type.select(self.env)],
                milestone.ticket.id
        )
        
        data = {
            'structured_milestones' : StructuredMilestone.select(self.env),
            'new_ticket_descriptor' : descriptor,
            'milestone' : milestone, 
            'action_controls' : self._get_action_controls(req, descriptor['ticket']),
        }
        return 'itteco_milestone_quick_edit.html', data, 'text/html'
		
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
        realm = req.args.get('obj_id')
        object_id = req.path_info.split('/')[-1]
        if realm == 'ticket':
            return self._comment_ticket(req, object_id)
        elif realm == 'milestone':
            return self._comment_milestone(req, object_id)
        raise ResourceNotFound('Unsupported realm %s.' % realm, 'Invalid Realm')

    def _comment_ticket(self, req, tkt_id):
        tkt = Ticket(self.env, tkt_id)
        if not tkt.exists:
            raise ResourceNotFound('Ticket %s does not exist.' % tkt_id,
                'Invalid Ticket Id')
	    req.perm.require('TICKET_MODIFY', Resource('ticket', tkt.resource))
        changes = TicketModule(self.env).rendered_changelog_entries(req, tkt)
        return 'itteco_ticket_comment.html', {'ticket': tkt, 'changes': changes}, 'text/html'

    def _comment_milestone(self, req, mil_id):
        milestone = StructuredMilestone(self.env, mil_id)
        if not milestone.exists:
            raise ResourceNotFound('Milestone %s does not exist.' % mil_id,
                                   'Invalid Milestone Name')
                                   
        req.perm.require('MILESTONE_MODIFY', milestone.resource)
        changes = TicketModule(self.env).rendered_changelog_entries(req, milestone.ticket)
        return 'itteco_milestone_comment.html', {'milestone': milestone, 'changes': changes}, 'text/html'
		
    def attach(self, req):
        path = req.path_info.split('/') 
        realm, obj_id = path[3:]
        
        obj_resource = Resource(realm, id=obj_id)
        attachment = Attachment(self.env, obj_resource.child('attachment'))
        
        req.perm(attachment.resource).require('ATTACHMENT_CREATE')
        if req.method =='POST':
            self._save_attachement(req, attachment)
            pass
        return 'itteco_attach_popup.html', {'resource': obj_resource}, 'text/html'
        
    def _save_attachement(self, req, attachment):
        from trac.web import RequestDone
        from trac.attachment import AttachmentModule, InvalidAttachment
        from trac.resource import get_resource_url
        from trac.timeline.web_ui import TimelineModule
        import os
        import unicodedata
        from trac.util.datefmt import pretty_timedelta

        
        response = None
        try:
            upload = req.args['attachment']
            if not hasattr(upload, 'filename') or not upload.filename:
                raise TracError(_('No file uploaded'))
            if hasattr(upload.file, 'fileno'):
                size = os.fstat(upload.file.fileno())[6]
            else:
                upload.file.seek(0, 2) # seek to end of file
                size = upload.file.tell()
                upload.file.seek(0)
            if size == 0:
                raise TracError(_("Can't upload empty file"))

            # Maximum attachment size (in bytes)
            max_size = AttachmentModule(self.env).max_size
            if max_size >= 0 and size > max_size:
                raise TracError(_('Maximum attachment size: %(num)s bytes',
                                  num=max_size), _('Upload failed'))

            # We try to normalize the filename to unicode NFC if we can.
            # Files uploaded from OS X might be in NFD.
            filename = unicodedata.normalize('NFC', unicode(upload.filename,
                                                            'utf-8'))
            filename = filename.replace('\\', '/').replace(':', '/')
            filename = os.path.basename(filename)
            if not filename:
                raise TracError(_('No file uploaded'))
            # Now the filename is known, update the attachment resource
            # attachment.filename = filename
            attachment.description = req.args.get('description', '')
            attachment.author = get_reporter_id(req, 'author')
            attachment.ipnr = req.remote_addr

            # Validate attachment
            for manipulator in AttachmentModule(self.env).manipulators:
                for field, message in manipulator.validate_attachment(req,
                                                                      attachment):
                    if field:
                        raise InvalidAttachment(_('Attachment field %(field)s is '
                                                  'invalid: %(message)s',
                                                  field=field, message=message))
                    else:
                        raise InvalidAttachment(_('Invalid attachment: %(message)s',
                                                  message=message))

            if req.args.get('replace'):
                try:
                    old_attachment = Attachment(self.env,
                                                attachment.resource(id=filename))
                    if not (old_attachment.author and req.authname \
                            and old_attachment.author == req.authname):
                        req.perm(attachment.resource).require('ATTACHMENT_DELETE')
                    if (not attachment.description.strip() and
                        old_attachment.description):
                        attachment.description = old_attachment.description
                    old_attachment.delete()
                except TracError:
                    pass # don't worry if there's nothing to replace
                attachment.filename = None
            attachment.insert(filename, upload.file, size)
            timeline = TimelineModule(self.env).get_timeline_link(req, attachment.date, pretty_timedelta(attachment.date), precision='second')
            response = {
                'attachment': {
                    'href': get_resource_url(self.env, attachment.resource, req.href),
                    'realm' : attachment.resource.parent.realm, 
                    'objid': attachment.resource.parent.id,
                    'filename' : filename, 
                    'size' : size, 
                    'author': attachment.author,
                    'description' : attachment.description,
                    'timeline' : timeline.generate().render().replace('<','&lt;').replace('>','&gt;')
                }
            }
        except (TracError, InvalidAttachment), e:
            response = {'error' : e.message }
        
        content = write(response)
        
        req.send_response(200)
        req.send_header('Content-Type', 'text/html')
        req.send_header('Content-Length', len(content))
        req.end_headers()
        req.write(content)
        raise RequestDone