from datetime import datetime

from genshi.builder import tag
from genshi.filters.transform import Transformer

import re
import sys

import trac
from trac.core import Component, implements, TracError
from trac.config import Option, ListOption

from trac.prefs import IPreferencePanelProvider
from trac.util.compat import set
from trac.util.text import CRLF
from trac.util.translation import _
from trac.util.datefmt import utc, to_timestamp, to_datetime, get_timezone, \
                              format_date, format_datetime

from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import INavigationContributor, add_script, add_stylesheet, add_link

from uuid import uuid4

import itteco
from itteco.calendar.model import CalendarType, Calendar, Event, TimeTrack
from itteco.init import IttecoEvnSetup
from itteco.ticket.api import IMilestoneChangeListener
from itteco.ticket.model import StructuredMilestone
from itteco.utils import json
from itteco.utils.render import get_powered_by_sign
 
class CalendarModule(Component):
    implements(INavigationContributor, IRequestHandler, ITemplateStreamFilter, \
        IMilestoneChangeListener, IPreferencePanelProvider)

    # INavigationContributor methods 
    def get_active_navigation_item(self, req):
        return 'calendar'

    def get_navigation_items(self, req):
        yield ('mainnav', 'calendar', tag.a(_('Calendar'), href=req.href.calendar(), accesskey=5))

    # IRequestHandler methods
    def match_request(self, req):
        if req.path_info.startswith('/calendar'):
            path = req.path_info.split('/')
            path_len = len(path)
            if path_len>2:
                req.args['cal_guid'] = path[2]
            return True

    def process_request(self, req):
        fmt = req.args.get('format','web')        
        if fmt=='web':
            return self._do_web_request(req)
        elif fmt=='json':
            obj_type = req.args['cal_guid']
            action = req.args.get('action', 'read')
            if req.authname=='anonymous':
                action = 'read'#only read operation is allowed for anonymous
            if obj_type=='calendars':
                self._process_json_calendars(action, req)
            if obj_type=='events':
                self._process_json_events(action, req)
            if obj_type=='tickets':
                self._process_json_tickets(action, req)
        elif fmt=='ics':
            self._process_ical_request(req)
            
    def _do_web_request(self, req):
        add_stylesheet(req, 'itteco/css/common.css')
        add_stylesheet(req, 'itteco/css/calendar.css')
        add_script(req, 'itteco/js/calendar.js')
        
        icshref = req.href.calendar(format='ics')
        add_link(req, 'alternate', icshref, _('iCalendar'), 'text/calendar', 'ics')

        return 'itteco_calendar_view.html', {}, None
    
    def _process_json_calendars(self, action, req):
        def cal_as_dict(cal):
            c= {
                'calendarId': cal.id, 
                'type': cal.type, 
                'name': cal.name, 
                'theme': cal.theme, 
                'alias': cal.alias,
                'ref': cal.ref
            }
            return c
        authname=req.authname
        if action=='read':
            shared = req.args.get('shared', False)
            kw= shared and {'type': CalendarType.Shared} or {'owner': authname}
            cals = Calendar.select(self.env, **kw)
            if shared:
                cals=[cal for cal in cals if cal.owner!=authname]
            req.write(json.write([cal_as_dict(cal) for cal in cals]))
        elif action=='save':
            cal = Calendar(self.env, req.args.get('calendarId') or None, authname)
            type = req.args.get('type', 'P')
            cal.name= req.args['name']
            cal.theme= req.args.get('theme') or 1
            if not CalendarType.isvalid(type) and cal.type != type:
                raise TracError(_(" Provided calendar type is invalid '%(type)s'", type= type))
            cal.type=type

            if type == CalendarType.Reference:
                ref_id = req.args.get('ref')
                if ref_id:
                    ref_cal = get_calendar_by_id(self.env, ref_id)
                    if ref_cal and ref_cal.type==CalendarType.Shared:
                        cal.ref = ref_cal.id

            if cal.id:
                if cal.owner!=authname:
                    raise TracError(_(" You have no rights to modify calendar '%(calendar)s'", calendar = cal.id))
                cal.update()
            else:
                cal.insert()
            send_json_resp(req, [cal_as_dict(cal),])
        elif action=='reset':
            cal = Calendar(self.env, req.args.get('calendarId'), authname)
            if cal.id:
                if cal.owner!=authname:
                    raise TracError(_(" You have no rights to modify calendar '%(calendar)s'", calendar = cal.id))
                cal.reset_alias()
            else:
                raise TracError(_(" You can not reset alias for not existing calendar"))
            send_json_resp(req, [cal_as_dict(cal),])
        elif action=='delete':
            cal_id = req.args.get('calendarId')
            cal = Calendar(self.env, cal_id, authname)
            cal.delete()
            send_json_resp(req, [cal_as_dict(cal),])
        else:
            raise TracError(_(" Unknow json action '%(action)s'", action = action))
    
    def _process_json_events(self, action, req):
        def event_as_dict(event):
            tt = event.time_track
            time = tt and tt.exists and tt.time or (event.dtend - event.dtstart).seconds/60
            
            e= {
                'eventId'    : event.id, 
                'startDate'  : event.dtstart, 
                'endDate'    : event.dtend, 
                'name'       : event.title, 
                'calendar'   : event.calendar, 
                'description': event.description,
                'ticket'     : event.ticket,
                'timetrack'  : tt and tt.exists,
                'auto'       : (tt and tt.auto and True) or (tt is None and True) or False,
                'time'       : '%02d:%02d' % (time/60, time % 60)
            }
            return e

        if action=='read':
            tstamp_attr = lambda x: long(req.args[x][:-3])
            dtstart = tstamp_attr('dtstart')
            dtend = tstamp_attr('dtend')
            events = [
                event_as_dict(event)
                for event in Event.select(self.env, req.authname, daterange=[dtstart, dtend])
            ]
            
            send_json_resp(req, events or [])
        elif action=='save':
            tz = get_timezone(req.session.get('tz'))
            getdate= lambda x: to_datetime(long(req.args[x][:-3]), tz)
            cal = Calendar(self.env, req.args['calendar'], req.authname)
            event_id = req.args.get('eventId') or None
            event = Event(self.env, event_id)

            if (event.calendar is None or event.calendar==cal.id) \
                and cal.type != CalendarType.Reference:
                
                event.title = req.args['name']
                event.description = req.args.get('description')
                event.calendar = cal.id
                event.ticket = req.args.get('ticket') or 0
                event.dtstart = getdate('startDate')
                event.dtend = getdate('endDate')
                
                if event_id:
                    event.update()
                else:
                    event.insert()
                    event_id = event.id
            else:
                event.calendar = cal.id # just to send referenced calendar id
            
            time_track_obj = TimeTrack(self.env, event_id, req.authname)
            time_track = req.args.get('timetrack') or None

            if time_track and time_track!='null':
                time = req.args.get('time')
                auto = req.args.get('auto')=='true' and 1 or 0
                time = time and time[-8:].split(':') or None
                if auto:
                    time = 0
                elif time and len(time)>1:
                    time = int(time[0])*60+int(time[1])
                
                time_track_obj.auto = auto
                time_track_obj.time = time
                if time_track_obj.exists:
                    time_track_obj.update()
                else:
                    time_track_obj.insert()
                event.time_track = time_track_obj
            else:
                if time_track_obj.exists:
                    time_track_obj.delete()

            send_json_resp(req, event_as_dict(event))
        elif action=='delete':
            event_id = req.args['eventId']
            event = Event(self.env, event_id)
            if event.exists:
                cal = Calendar(self.env, event.calendar, req.authname)                
                if not cal.exists or cal.type == CalendarType.Reference:
                    raise TracError(_("You have no rights to modify calendar '%(calendar)s'", calendar = cal.id))
                event.delete()
            send_json_resp(req, {'eventId': event.id})
        else:
            raise TracError(_(" Unknow json action '%(action)s'", action = action))

    def _process_json_tickets(self, action, req):
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
           [req.authname,]+final_statuses)

        tickets = [ticket_as_dict(tktId, summary) for tktId, summary in cursor]

        send_json_resp(req, tickets)

    def _process_ical_request(self, req):
        req.send_response(200)
        req.send_header('Content-Type', 'text/calendar;charset=utf-8')
        req.end_headers()

        def escape_value(text): 
            s = ''.join(map(lambda c: (c in ';,\\') and '\\' + c or c, text))
            return '\\n'.join(re.split(r'[\r\n]+', s))

        def write_prop(name, value, params={}):
            text = ';'.join([name] + [k + '=' + v for k, v in params.items()]) \
                 + ':' + escape_value(value)
            firstline = 1
            while text:
                if not firstline: text = ' ' + text
                else: firstline = 0
                req.write(text[:75] + CRLF)
                text = text[75:]

        def write_date(name, value, params={}):
            params['VALUE'] = 'DATE'
            write_prop(name, format_date(value, '%Y%m%d', req.tz), params)

        def write_utctime(name, value, params={}):
            write_prop(name, format_datetime(value, '%Y%m%dT%H%M%SZ', utc),
                       params)

        cal_guid = req.args.get('cal_guid')
        events=[]
        user_name = req.authname
        if(cal_guid):
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute("""
                SELECT sid
                  FROM session_attribute
                 WHERE name='cal_alias' AND value=%s""",
               (cal_guid,)
            )
            row = cursor.fetchone()
            if row:
                user_name, = row
        events=Event.select(self.env, user_name)
                
        write_prop('BEGIN', 'VCALENDAR')
        write_prop('VERSION', '2.0')
        write_prop('PRODID', '-//Edgewall Software//NONSGML Trac %s//Itteco Plugin %s//EN'
                   % (trac.__version__,itteco.__version__))
        write_prop('METHOD', 'PUBLISH')
        write_prop('X-WR-CALNAME', '%s - Calendar' % user_name )

        host = req.base_url[req.base_url.find('://') + 3:]

        for e in events:
            uid = '<%s/calendar/%s/%s@%s>' % (req.base_path, e.calendar, e.id,host)
            write_prop('BEGIN', 'VEVENT')
            write_prop('UID', uid)
            write_utctime('DTSTAMP', e.dtstart)
            write_utctime('DTSTART', e.dtstart)
            write_utctime('DTEND', e.dtend)
            write_prop('SUMMARY', "%s" % (e.title))
            write_prop('URL', req.base_url + '/calendar/web')
            if e.description:
                write_prop('DESCRIPTION', e.description)
            write_prop('END', 'VEVENT')
            
        write_prop('END', 'VCALENDAR')
    
        
    def filter_stream(self, req, method, filename, stream, data):
        if req.path_info.startswith('/calendar'):
            data['transformed']=1
            stream |=Transformer('//*[@id="footer"]/p[@class="right"]').before(get_powered_by_sign())
      
        return  stream
    #IMilestoneChangeListener methods
    def milestone_created(self, milestone):
        pass

    def milestone_changed(self, milestone, old_values):
        old_name = old_values and old_values.get('name') or None
        if old_name:
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute(
                """UPDATE time_track
                      SET event_id=%s
                    WHERE event_id=%s""", 
                (milestone.name, old_name)
            )
            db.commit()
    def milestone_deleted(self, milestone):
        pass
    
    #IPreferencePanelProvider methods
    def get_preference_panels(self, req):
        yield ('calendar', 'Calendar Prefs')

    def render_preference_panel(self, req, panel):
        if req.method == 'POST':
            action = req.args.get('reset_cal_alias')
            if action:
                req.session['cal_alias'] = str(uuid4())
            req.redirect(req.href.prefs(panel or None))

        return 'itteco_cal_prefs.html', {
            'settings': {'session': req.session, 'session_id': req.session.sid},
        }
        
def get_calendar_by_id(env, cal_id):
    cals= Calendar.select(env, id=cal_id)
    return cals and cals[0] or None
    
def send_json_resp(req, obj):
    req.send_response(200)
    req.send_header('Content-Type', 'application/json')
    req.end_headers()
    req.write(json.write(obj))
