from datetime import datetime, timedelta

from genshi.builder import tag
from genshi.filters.transform import Transformer

import re

from trac.core import Component, implements
from trac.config import Option, ListOption

from trac.resource import ResourceNotFound
from trac.util.text import CRLF
from trac.util.translation import _
from trac.util.datefmt import FixedOffset, utc, to_timestamp, to_datetime, get_timezone, \
                              format_date, format_datetime

from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import INavigationContributor, add_script, add_stylesheet, add_link

from itteco.calendar.model import CalendarType, Calendar, Event, TimeTrack
from itteco.calendar.util import *

from itteco.init import IttecoEvnSetup
from itteco.ticket.api import IMilestoneChangeListener
from itteco.ticket.model import StructuredMilestone
from itteco.utils.render import get_powered_by_sign
 
class CalendarModule(Component):
    implements(INavigationContributor, IRequestHandler, ITemplateStreamFilter, \
        IMilestoneChangeListener)
        
    # INavigationContributor methods 
    def get_active_navigation_item(self, req):
        return 'calendar'

    def get_navigation_items(self, req):
        yield ('mainnav', 'calendar', tag.a(_('Calendar'), href=req.href.calendar(), accesskey=5))

    # IRequestHandler methods
    def match_request(self, req):           
        return req.path_info.startswith('/calendar')

    def process_request(self, req):
        fmt = req.args.get('format','web')
        if fmt=='ics':
            self._process_ical_request(req)
            
        return self._render_ui(req)
    
    def _render_ui(self, req):
        add_stylesheet(req, 'itteco/css/fullcalendar.css')
        add_stylesheet(req, 'itteco/css/thickbox/thickbox.css')
        add_stylesheet(req, 'itteco/css/common.css')
        add_stylesheet(req, 'itteco/css/calendar.css')

        add_script(req, 'itteco/js/thickbox/thickbox.js')
        add_script(req, 'itteco/js/jquery.ui/ui.core.js')
        add_script(req, 'itteco/js/jquery.ui/ui.draggable.js')
        add_script(req, 'itteco/js/jquery.ui/ui.droppable.js')
        add_script(req, 'itteco/js/jquery.ui/ui.resizable.js')
        add_script(req, 'itteco/js/jquery.ui/ui.datepicker.js')
        add_script(req, 'itteco/js/jquery.ui/ui.slider.js')
        add_script(req, 'itteco/js/jquery.timepicker.js')
        add_script(req, 'itteco/js/jquery.rpc.js')
        add_script(req, 'itteco/js/jquery.jeditable.js')
        add_script(req, 'itteco/js/fullcalendar.min.js')
        add_script(req, 'itteco/js/calendar.js')
    
        icshref = req.href.calendar(format='ics')
        add_link(req, 'alternate', icshref, _('iCalendar'), 'text/calendar', 'ics')

        return 'itteco_calendar_view.html', {}, None

            
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
def get_calendar_by_id(env, cal_id):
    cals= Calendar.select(env, id=cal_id)
    return cals and cals[0] or None
