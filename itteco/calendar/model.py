from datetime import date, datetime, timedelta
import sys

from trac.util.datefmt import utc, utcmax, to_timestamp
from trac.resource import ResourceNotFound
from uuid import uuid4
from itteco.utils import json, Enumeration


CalendarType = Enumeration(
    "CalendarType",
    [
        ("Private", "P"), #private calendar
        ("Shared", "S"), #shared calendar
        ("Reference", "R") #reference to shared calendar
    ]
)
    

class Calendar(object):

    def __init__(self, env, cal_id=None, owner=None, db=None):
        self.env = env
        self._exists = False
        self.ref=self.name= self.type= self.alias =self.theme= None
        self.owner= owner
        self.id=cal_id
        if cal_id:
            self._fetch(cal_id, owner, db)
            
    exists = property(lambda self: self._exists)
    
    def _fetch(self, cal_id, owner, db=None):
        row = None
        db = db or self.env.get_db_cnx()
        
        row = self._get_row(cal_id, owner, db)
        if row:
            self._from_db_row(row)
        
    def _get_row(self, cal_id, owner, db):
        cursor = db.cursor()
        cursor.execute("SELECT id, name, owner, type, alias, theme, ref, created, modified " +
            "FROM calendar WHERE id=%s AND owner=%s", (cal_id, owner))
        return cursor.fetchone()
        
    def _from_db_row(self, row):
        self._exists = True
        types = [int, T, T, T, T, T, T, dt, dt]
        cal_id, name, owner, type, alias, theme, ref, created, modified = [t(v) for t, v in zip(types, row)]
        self.id = cal_id
        self.name =  name
        self.owner = owner
        self.type = type
        self.theme= theme
        self.ref= ref
        self.alias = self._old_alias= alias
        self.time_created = created
        self.time_modified = modified

    @staticmethod    
    def select(env, **kwargs):
        cursor = env.get_db_cnx().cursor()
        where_smt = ""
        if kwargs:
           where_smt = "WHERE "+ " AND ".join(["%s=%%s" % k for k in kwargs.iterkeys()])

        cursor.execute("SELECT id, name, owner, type, alias, theme, ref, created, modified " +
            "FROM calendar "+ where_smt, kwargs.values())
            
        cals = []
        for row in cursor:
            cal = Calendar(env)
            cal._from_db_row(row)
            cals.append(cal)
        return cals

    def insert(self, db=None):
        """Add calendar to database"""
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)
        
        self.time_created = self.time_modified = datetime.now(utc)
        self.alias = self.alias or str(uuid4())
        types = [T, T, T, T, int, T, to_timestamp, to_timestamp]
        params = [t(v) for t, v in zip(types, (self.name, self.owner, self.type, self.alias, \
                        self.theme, self.ref, self.time_created, self.time_modified))]
        cursor = db.cursor()
        cursor.execute("INSERT INTO calendar(name, owner, type, alias, theme,"+
            "ref,created, modified) VALUES (%s)" % ("%s,"*len(params))[:-1],params)
        cal_id = db.get_last_id(cursor, 'calendar')
        if handle_ta:
            db.commit()

        self.id = cal_id
        return self.id

    def update(self, db=None):
        """Update calendar in database"""
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)
        self.time_modified = datetime.now(utc)
        types = [T, T, T, int, T, to_timestamp, to_timestamp, int, T]
        
        cursor = db.cursor()       
        cursor.execute("UPDATE calendar SET name=%s, type=%s, alias=%s,"+
            " theme=%s, ref=%s, created=%s, modified=%s WHERE id=%s AND owner=%s",
                       [t(v) for t, v in zip(types, (self.name, self.type, self.alias, \
                        self.theme, self.ref, self.time_created, self.time_modified, \
                        self.id, self.owner))])
        if handle_ta:
            db.commit()

        return True

    def delete(self, db=None):
        """Delete calendar from database"""
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)

        cursor = db.cursor()
        cursor.execute("DELETE FROM cal_event WHERE calendar_id IN (SELECT id FROM calendar WHERE id=%s OR ref=%s)", (self.id, self.id))
        cursor.execute("DELETE FROM calendar WHERE id=%s OR ref=%s", (self.id, self.id))
        if handle_ta:
            db.commit()
        return True
    
    def reset_alias(self, db=None):
        """Reset alias of the calendar"""
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)
        self.alias = str(uuid4())
        cursor = db.cursor()
        cursor.execute("UPDATE calendar SET alias=%s WHERE id=%s AND owner=%s", (self.alias, self.id, self.owner))
        if handle_ta:
            db.commit()
        return True    
class MilestonesCalendar(object):
    def __init__(self, env):
        self.env = env
        self.id = sys.maxint
        self.name =  "Project milestones"
        self.owner = "system"
        self.type = CalendarType.Shared
        self.theme = self.alias = self.ref = None
        
    def events(self, dtstart, dtend):
        db = self.env.get_db_cnx()
        sql = """SELECT name, due, completed, description 
                   FROM milestone 
                  WHERE due BETWEEN %s AND %s
                     OR completed BETWEEN %s AND %s"""
        cursor = db.cursor()
        cursor.execute(sql, [dtstart, dtend]*2)
        events = []
        delta = timedelta(minutes=45)
        for name, due, completed, description in cursor:
            event= Event(self.env)
            event.id= name
            event.title= completed and name + '[Completed]' or name +'[Due]'
            event.description= description
            event.calendar= self.id
            ts = completed or due
            ts = ts and datetime.fromtimestamp(int(ts), utc) or None
            event.dtstart= ts
            event.dtend= ts and ts+delta or None
            event.timetrack = None
            events.append(event)
        return events

class Event(object):

    def __init__(self, env, event_id=None, db=None):
        self.env = env
        self.time_track = None
        self.title = self.description = self.calendar = self.ticket= \
            self.dtstart = self.dtend = None
        if event_id is not None:
            self._fetch(event_id, db)
        self.id = event_id

    exists = property(lambda self: self.id is not None)
        
    def _fetch(self, event_id, db=None):
        row = None
        db = db or self.env.get_db_cnx()

        cursor = db.cursor()
        cursor.execute(
            """SELECT id, title, description, calendar_id, 
                      ticket, dtstart, dtend, created, modified
                 FROM all_cal_events WHERE id=%s""",
            (event_id,)
        )

        row = cursor.fetchone()
        if not row:
            raise ResourceNotFound('Event %s does not exist.' % event_id,
                                   'Invalid Event Id')

        self._from_db_row(row)
    
    def _from_db_row(self, row):
        types = [T, T, T, nvl_int, nvl_int, dt, dt, dt, dt, T]
        event_id, title, description, calendar_id, ticket, dtstart, dtend, created, modified = \
            [t(v) for t, v in zip(types, row)]
        self.id = event_id
        self.title = self._old_title = title
        self.description= self._old_description = description
        self.calendar = self._old_calendar = calendar_id
        self.ticket = self._old_ticket = ticket
        self.dtstart = self._old_dtstart = dtstart
        self.dtend = self._old_dtend = dtend
        self.time_created = created
        self.time_modified = modified

    def insert(self, db=None):
        """Add event to database"""
        assert not self.exists, 'Cannot insert an existing event'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)

        self.time_created = self.time_modified = datetime.now(utc)
        types = [T, T, int, int, to_timestamp, to_timestamp, to_timestamp, to_timestamp]
        
        cursor = db.cursor()
        cursor.execute("INSERT INTO cal_event(title, description, calendar_id, ticket, dtstart,"+
            " dtend, created, modified) VALUES (%s)" % ("%s,"*8)[:-1],
                       [t(v) for t, v in zip(
                            types, 
                            (
                                self.title, 
                                self.description, 
                                self.calendar, 
                                self.ticket, 
                                self.dtstart, 
                                self.dtend, 
                                self.time_created, 
                                self.time_modified
                            ))
                        ])
        event_id = db.get_last_id(cursor, 'cal_event')

        if handle_ta:
            db.commit()

        self.id = event_id
        return self.id

    def delete(self, db=None):
        """Delete event from database"""
        assert self.exists, 'Cannot delete none existing event'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)
        
        cursor = db.cursor()
        cursor.execute("DELETE FROM cal_event WHERE id=%s",(self.id,))
        if handle_ta:
            db.commit()
        return self.id
        
    @staticmethod    
    def select(env, owner, daterange=None):
        def t_stamp(t):
            if isinstance(t, datetime):
                return to_timestamp(t)
            elif isinstance(t, (int,long,float)):
                return t
        sql = """
              SELECT ev.*, ev.id as event_id, tt.owner, tt.auto, tt.time
                FROM
                      (SELECT e.id as id, e.title, e.description, e.calendar_id, e.ticket, 
                              e.dtstart as dtstart, e.dtend as dtend, e.created, e.modified
                         FROM all_cal_events as e, calendar as c 
                        WHERE e.calendar_id = c.id AND c.owner=%s
                        UNION
                       SELECT e.id as id, e.title, e.description, c.id, e.ticket, 
                              e.dtstart as dtstart, e.dtend as dtend, e.created, e.modified
                         FROM all_cal_events as e, calendar as c 
                        WHERE e.calendar_id = c.ref AND c.owner=%s) as ev
                      LEFT OUTER JOIN time_track as tt ON tt.owner = %s AND tt.event_id = ev.id"""
        params = [owner,]*3
        
        where_smt = ""
        if daterange:
           where_smt = " WHERE (dtstart BETWEEN %s AND %s) OR (dtend BETWEEN %s AND %s)"
           params.extend(daterange*2)

        cursor = env.get_db_cnx().cursor()
        cursor.execute(sql +where_smt, params)
        env.log.debug((sql +where_smt) % tuple(params))
        events = []
        for row in cursor:
            event = Event(env)
            event._from_db_row(row[:-4])
            
            time_track = TimeTrack(env)
            time_track._from_db_row(row[-4:])
            event.time_track = time_track
            
            events.append(event)
        return events
    

    def update(self, db=None):
        """Add event to database"""
        assert self.exists, 'Cannot update ticket that was not inserted'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)

        self.time_modified = datetime.now(utc)
        types = [T, T, int, int, to_timestamp, to_timestamp, to_timestamp, to_timestamp, int]
        
        cursor = db.cursor()       
        cursor.execute(
            """UPDATE cal_event 
                  SET title=%s, description=%s, calendar_id=%s, ticket=%s, dtstart=%s, dtend=%s,
                      created=%s, modified=%s 
                WHERE id=%s""",
           [t(v) for t, v in zip(types, (self.title, self.description, self.calendar, self.ticket, \
                self.dtstart, self.dtend, self.time_created, self.time_modified, self.id))])
        if handle_ta:
            db.commit()
        return True

    def __hash__(self):
        return hash(self.id)

    def __cmp__(self, other):
        # sort first on start datetime, then on public id
        if not isinstance(other, Event):
            return 1
        return cmp(
            (self.dtstart, self.dtend, self.id),
            (other.dtstart, other.dtend, other.id))
    
    def export(self, private=False):
        """Exports the event as an icalendar.Event.

        Setting private to True will hide all information except date/time
        information. This should be used for private events when exporting
        is done by somebody who does not have full rights to the event

        e = icalendar.Event()
        if not self.allday:
            e.add('dtstart', self.dtstart)
            # exporting duration directly instead of dtend
            # seems to confuse some clients, like KOrganizer,
            # so calculate dtend instead
            e.add('dtend', self.dtstart + self.duration)
        else:
            # all day event
            # create dtstart with VALUE=DATE property
            dtstart_prop = icalendar.vDate(self.dtstart.date())
            dtstart_prop.params['VALUE'] = icalendar.vText('DATE')
            e.add('dtstart', dtstart_prop, encode=0)
            # now create dtend with VALUE=DATE property
            dtend = self.dtstart + self.duration
            dtend_prop = icalendar.vDate(dtend)
            dtend_prop.params['VALUE'] = icalendar.vText('DATE')
            e.add('dtend', dtend_prop, encode=0)
        if self.recurrence is not None:
            r = self.recurrence
            d = {'freq': r.ical_freq, 'interval': r.interval}
            if r.count is not None:
                d['count'] = r.count
            if r.until is not None:
                d['until'] = r.until
            e.add('rrule', icalendar.vRecur(d))
        if self.transparent:
            e.add('transp', 'TRANSPARENT')
        else:
            e.add('transp', 'OPAQUE')
        e.add('uid', self.unique_id)
        e.add('class', self.access)
        if private:
            # Hide all non-time information as it may be sensitive.
            e.add('summary', _("Private Event"))
            return e

        e.add('summary', self.title)
        if self.description:
            e.add('description', self.description)
        if self.location:
            e.add('location', self.location)
        if self.categories:
            e.set_inline('categories', list(self.categories))
        if self.document:
            e.add('attach', self.document)
        e.add('status', self.status)
        return e
        """
        
        pass

class TimeTrack(object):

    def __init__(self, env, event_id=None, owner=None, db=None):
        self.env = env
        self._exists = False
        self.id = event_id
        self.owner = owner
        self.auto = 1
        self.time = 0
        if event_id is not None and owner is not None:
            self._fetch(event_id, owner, db)
        
    def _fetch(self, event_id, owner, db=None):
        row = None
        db = db or self.env.get_db_cnx()

        cursor = db.cursor()
        cursor.execute(
            """SELECT event_id, owner, auto, time
                 FROM time_track
                WHERE event_id=cast(%s as text) AND owner=%s""",(event_id, owner))

        row = cursor.fetchone()
        if row:
            self._from_db_row(row)
            self._exists = True
    
    def _from_db_row(self, row):
        types = [T, T, nvl_int, nvl_int]
        event_id, owner, auto, time = [t(v) for t, v in zip(types, row)]
        self.id = event_id
        self.owner = owner
        self.auto = auto
        self.time = time
        self._exists = auto or time>0
        
    def insert(self, db=None):
        """Add event time track info to database"""
        assert not self.exists, 'Cannot insert an existing time trac information'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)

        types = [T, T, int, int]
        
        cursor = db.cursor()
        cursor.execute("INSERT INTO time_track(event_id, owner, auto, time) VALUES (%s,%s,%s,%s)",
                       [t(v) for t, v in zip(
                            types, 
                            (
                                self.id, 
                                self.owner, 
                                self.auto, 
                                self.time
                            ))
                        ])
        if handle_ta:
            db.commit()

    def delete(self, db=None):
        """Delete event time track from database"""
        assert self.exists, 'Cannot delete none existing event time track'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)
        
        cursor = db.cursor()
        cursor.execute("DELETE FROM time_track WHERE event_id=%s AND owner=%s",(self.id, self.owner))
        if handle_ta:
            db.commit()

    def update(self, db=None):
        """Update event time track in database"""
        assert self.exists, 'Cannot update event time track that was not inserted'
        db, handle_ta = db and (db, False) or (self.env.get_db_cnx(), True)

        types = [int, int, T, T]
        
        cursor = db.cursor()       
        cursor.execute(
            """UPDATE time_track
                  SET auto=%s, time=%s
                WHERE event_id=%s AND owner=%s""",
           [t(v) for t, v in zip(types, (self.auto, self.time, self.id, self.owner))])
        if handle_ta:
            db.commit()
        return True

    exists = property(lambda self: self._exists)
nvl_int = lambda x: x is not None and int(x) or 0
T = lambda x:x
dt = lambda x: x and datetime.fromtimestamp(x, utc) or None