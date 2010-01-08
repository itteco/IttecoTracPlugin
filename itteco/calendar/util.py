from datetime import datetime
from trac.util.datefmt import format_datetime, parse_date, utc

_TRUE_VALUES = ('yes', 'true', 'enabled', 'on', 'aye', '1', 1, True)

def parse_datetime(val, tz):
    if isinstance(val, datetime):
        return val
    return parse_date(val, tz)
    
def time_in_minutes(val):
    time = val and val.split(':') or None
    if len(time)>1:
        return int(time[0])*60+int(time[1])
    return int(time)

def bool_to_int(val):
    return val in _TRUE_VALUES and 1 or 0
    
def cal_as_dict(cal, username):
    c= {
        'id'    : cal.id, 
        'type'  : cal.type, 
        'name'  : cal.name, 
        'theme' : cal.theme, 
        'alias' : cal.alias,
        'own'   : cal.owner==username,
        'ref'   : cal.ref,
        'owner' : cal.owner,
        'username': username
    }
    return c
    
def event_as_dict(event, own=False):
    tt = event.time_track
    time = 0
    if tt and tt.exists:
        time = tt.time
    else:
        if event.allday:
            time = 24*60#all day event is 24 hours long
        else:
            time = (event.dtend - event.dtstart).seconds/60
    
    e= {
        'id'         : event.id, 
        'start'      : format_datetime(event.dtstart,'iso8601', utc),
        'end'        : format_datetime(event.dtend,'iso8601', utc),
        'allDay'     : event.allday==1,
        'name'       : event.title, 
        'own'        : own,
        'calendar'   : event.calendar, 
        'description': event.description,
        'ticket'     : event.ticket,
        'timetrack'  : tt and True or False,
        'auto'       : (tt and tt.auto and True) or (tt is None and True) or False,
        'time'       : '%02d:%02d' % (time/60, time % 60)
    }
    return e