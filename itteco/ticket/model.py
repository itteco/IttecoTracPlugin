from copy import copy
from datetime import datetime
from trac.resource import *
from trac.ticket.model import Ticket, Milestone
from trac.util.datefmt import utc, utcmax, to_timestamp, to_datetime
from trac.util.translation import _
from trac.util.compat import set, sorted
from trac.util import embedded_numbers, partition
from trac.wiki.model import WikiPage

from itteco.ticket.api import MilestoneSystem
from itteco.init import IttecoEvnSetup

_sql_select_wiki = "SELECT value FROM ticket_custom WHERE ticket=%s AND name='wiki_ref'"
_sql_insert_wiki = "INSERT into ticket_custom(value, name, ticket) VALUES(%s, 'wiki_ref', %s)"
_sql_update_wiki = "UPDATE ticket_custom SET value=%s WHERE ticket=%s AND name='wiki_ref'"
_sql_delete_wiki = "DELETE FROM ticket_custom WHERE ticket=%s AND name='wiki_ref'"

class TicketLinks(object):
    """A model for the ticket links used for tickets tracebility."""    

    def __init__(self, env, tkt, db=None):    
        self.env = env
        if not isinstance(tkt, Ticket):
            tkt = Ticket(self.env, tkt)
        self.tkt = tkt
        
        db = db or self.env.get_db_cnx()
        cursor = db.cursor()
        
        self.outgoing_links = set([num for num, in TicketLinks._fetch_raw_refs(self.tkt.id, cursor)])
        self._old_outgoing_links = copy(self.outgoing_links)
        
        self.incoming_links = set([num for num, in TicketLinks._fetch_raw_refs(self.tkt.id, cursor, reverse = True)])
        cursor.execute("SELECT value FROM ticket_custom WHERE ticket=%s AND name='wiki_ref'", (self.tkt.id,))
        row = cursor.fetchone()
        self.wiki_links = set()
        if(row and len(row)>0):
            s = row[0].strip() 
            if s:
                self.wiki_links = set(s.split(','))

    def save(self, author=None, comment='', when=None, db=None):
        """Save ticket links."""
        if when is None:
            when = datetime.now(utc)
        when_ts = to_timestamp(when)
        
        handle_commit = False
        if db is None:
            db = self.env.get_db_cnx()
            handle_commit = True
            
        cursor = db.cursor()        
        if not isinstance(self.outgoing_links, set):
            self.outgoing_links = set(self.outgoing_links)
        added_ids = self.outgoing_links - self._old_outgoing_links
        outdated_ids = self._old_outgoing_links - self.outgoing_links

        for new_id in added_ids:
            ref_ticket = Ticket(self.env,  new_id)
            if(ref_ticket.exists):
                cursor.execute('INSERT INTO tkt_links (src, dest) VALUES (%s, %s)', (self.tkt.id, ref_ticket.id))
        
        if(outdated_ids):
            if(len(outdated_ids)>1):            
                cursor.execute('DELETE FROM tkt_links WHERE src=%%s AND dest IN (%s)' % ("%s,"*len(outdated_ids))[:-1], ((self.tkt.id,) + tuple(outdated_ids)))
            else:
                cursor.execute('DELETE FROM tkt_links WHERE src=%s AND dest=%s', (self.tkt.id, outdated_ids.pop()))
        
        if(self.wiki_links):
            wikis = ','.join([ wiki_name for wiki_name in self.wiki_links if WikiPage(self.env, wiki_name).exists])

            cursor.execute(_sql_select_wiki, (self.tkt.id,))
            if(cursor.fetchone()):
                cursor.execute(_sql_update_wiki, (wikis, self.tkt.id))
            else:
                cursor.execute(_sql_insert_wiki, (wikis, self.tkt.id))
        else:
            cursor.execute(_sql_delete_wiki, (self.tkt.id, ))
        self._old_outgoing_links = copy(self.outgoing_links)
        if handle_commit:
            db.commit()

    def __eq__(self, other):
        if isinstance(other, LinkedTicket):
            return self.tkt.id == other.tkt.id
        return self == other

    @staticmethod
    def _fetch_raw_refs(tkt_id, cursor, table='tkt_links', reverse=False):
        params = ['dest', table, 'src']
        if(reverse):
            params.reverse()
        params.append(params[0])
        sql = "SELECT %s FROM %s WHERE %s=%%s ORDER BY %s" % tuple(params)
        cursor.execute(sql, (tkt_id, ))
        return cursor.fetchall()

class StructuredMilestone(object):
    """The model for structured milestone."""
    __proxy_attrs__ = ['name', 'due', 'completed', 'description', 'resource', 'exists', 'is_completed', 'is_late']
    _kids = None
    _level = None
    def __init__(self, env, milestone=None, db=None):
        self.env = env
        self.fields = MilestoneSystem(self.env).get_milestone_fields()
        self.values = self._old = {}

        if not isinstance(milestone, Milestone):
            milestone = Milestone(env, milestone)
            if milestone.exists:
                self._fetch(milestone.name, db)
            
        self.milestone = milestone
    
    def __getattribute__(self, name):
        if name in object.__getattribute__(self, "__proxy_attrs__"):
            return getattr(object.__getattribute__(self, "milestone"), name)
        return object.__getattribute__(self, name)
    
    def __setattr__(self, name, value):
        if name in object.__getattribute__(self, "__proxy_attrs__"):
            setattr(object.__getattribute__(self, "milestone"), name, value)
        else:
            self.__dict__[name]=value
    
    parent = property(fget= lambda self: self.values.get('parent'))
    is_started = property(fget=lambda self: self.values.get('started') is not None)
    level = property(fget = lambda self: self._get_level(), fset = lambda self, val: self._set_level(val))
    can_be_closed = property(lambda self: self._can_be_closed())
    kids = property (lambda self: self._get_kids())

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        """Log ticket modifications so the table ticket_change can be updated"""
        if name in self.values and self.values[name] == value:
            return
        if name not in self._old: # Changed field
            self._old[name] = self.values.get(name)
        elif self._old[name] == value: # Change of field reverted
            del self._old[name]
        if value:
            if isinstance(value, list):
                raise TracError(_("Multi-values fields not supported yet"))
            field = [field for field in self.fields if field['name'] == name]
            if field and field[0].get('type') != 'textarea':
                value = value.strip()
        self.values[name] = value
    
    def _fetch(self, name, db=None):
        if not  self.fields:
            return
        if not db:
            db = self.env.get_db_cnx()
            
        cursor = db.cursor()
        cursor.execute("SELECT name, value "
                        " FROM milestone_custom"
                       " WHERE milestone=%s", (name,))
        self._custom_fields_from_collection(cursor)
                
    def _custom_fields_from_collection(self, data):
        field_names = [f['name'] for f in self.fields]
        for name, value in data:
            if name in field_names and value is not None:
                self.values[name] = value        

    def _get_kids(self):
        if self._kids is None:
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute("SELECT m.name "
                            " FROM milestone m,"
                                 " milestone_custom mc"
                           " WHERE m.name=mc.milestone"
                             " AND mc.name='parent'"
                             " AND mc.value=%s", (self.name,))
            self._kids = [StructuredMilestone(self.env, name) for name, in cursor]
        return self._kids

    
    def _can_be_closed(self):
        kids = self.kids
        if kids:
            for kid in kids:
                if not kid.is_completed:
                    return False
        return True

    def _get_level(self):
        if self._level:
            return self._level
        lev = 0
        if self.parent:
            parent_milestone = StructuredMilestone(self.env, self.parent)
            if parent_milestone.exists:
                lev = parent_milestone.level['index'] +1
        self._level = {'index':lev, 'label': self._get_level_label(lev)}
        return self._level
    
    def _set_level(self, lev):
        int_lev = int(lev)
        self._level = {'index':int_lev, 'label': self._get_level_label(int_lev)}
        
    def _get_level_label(self, idx):
        label = 'undefined'
        levels = IttecoEvnSetup(self.env).milestone_levels
        if levels and idx < len(levels):
            label = levels[idx]
        return label

    def delete(self, retarget_to=None, author=None, db=None):
        handle_commit = False
        if not db:
            db = self.env.get_db_cnx()
            handle_commit = True

        cursor = db.cursor()
        cursor.execute("DELETE FROM milestone_custom WHERE milestone=%s", (self.name))
        cursor.execute("UPDATE milestone_custom SET value=%s WHERE name='parent' AND value=%s", (retarget_to, self.name))

        self.milestone.delete(retarget_to, author, db)
        if handle_commit:
            db.commit()
            
        listeners = IttecoEvnSetup(self.env).change_listeners
        for listener in listeners:
            listener.milestone_deleted(self)


    def insert(self, db=None):
        assert self.name, 'Cannot create milestone with no name'
        handle_commit = False
        if not db:
            db = self.env.get_db_cnx()
            handle_commit = True

        self.milestone.insert(db)
        cursor = db.cursor()
        cursor.executemany("INSERT INTO milestone_custom (milestone,name,value) "
                           "VALUES (%s,%s,%s)", [(self.name, field['name'], self[field['name']])
                                                 for field in self.fields])
        if handle_commit:
            db.commit()
            
        listeners = IttecoEvnSetup(self.env).change_listeners
        for listener in listeners:
            listener.milestone_created(self)


    def update(self, db=None):
        self.env.log.debug("Updating '%s' milestone" %self)
        assert self.name, 'Cannot update milestone with no name'
        handle_commit = False
        if not db:
            db = self.env.get_db_cnx()
            handle_commit = True
            
        _old_name = self.milestone.name
        
        self.milestone.update(db)
        cursor = db.cursor()
        if self.name!=_old_name:
            cursor.execute("UPDATE milestone_custom SET milestone=%s WHERE name=%s", (self.name, _old_name))
            cursor.execute("UPDATE milestone_custom SET value=%s WHERE name='parent' AND value=%s", (self.name, _old_name))

        field_names = [f['name'] for f in self.fields]
        for name in self._old.keys():
            if name in field_names:
                cursor.execute("SELECT * FROM milestone_custom " 
                               "WHERE milestone=%s and name=%s", (self.name, name))
                if cursor.fetchone():
                    cursor.execute("UPDATE milestone_custom SET value=%s "
                                   "WHERE milestone=%s AND name=%s",
                                   (self[name], self.name, name))
                else:
                    cursor.execute("INSERT INTO milestone_custom (milestone,name,"
                                   "value) VALUES(%s,%s,%s)",
                                   (self.name, name, self[name]))

        if handle_commit:
            db.commit()
        old_values = self._old
        self._old={}                
        listeners = IttecoEvnSetup(self.env).change_listeners
        for listener in listeners:
            listener.milestone_changed(self, old_values)
    
    @staticmethod
    def select(env, include_completed=True, db=None):
        if not db:
            db = env.get_db_cnx()
            
        milestones = dict([(milestone.name, milestone) for milestone in Milestone.select(env, include_completed, db)])
        if milestones:
            sql = "SELECT milestone, name, value \
                     FROM milestone_custom m \
                    WHERE milestone IN (%s)" % (("%s,"*len(milestones))[:-1])
        cursor = db.cursor()
        cursor.execute(sql, milestones.keys())
        grouped = partition(((name, value), milestone) for milestone, name, value in cursor)
        structured_milestones = []
        for milestone, name_value_paires in grouped.iteritems():
            structured_milestone = StructuredMilestone(env, milestones[milestone])
            structured_milestone._custom_fields_from_collection(name_value_paires)
            structured_milestones.append(structured_milestone)
        return StructuredMilestone.reorganize(structured_milestones)
           
    @staticmethod
    def reorganize(milestones):
        if not milestones:
            return milestones
        for milestone in milestones:
            milestone._kids = []

        grouped = partition((milestone, milestone.parent) for milestone in milestones)
        roots = []
        name_to_struct = {}
        delayed_items ={}
        for parent, kids in grouped.iteritems():
            target = roots
            if parent:
                if name_to_struct.has_key(parent):
                    target =  name_to_struct[parent].kids
                else:
                    target = delayed_items.setdefault(parent, [])
            for child in kids:
                child.kids.extend(delayed_items.pop(child.name,[]))
                name_to_struct[child.name] = child
                target.append(child)
        return StructuredMilestone._deep_sort(roots)
    
    @staticmethod
    def _deep_sort(mils):
        def milestone_order(m):
            return (m.completed or utcmax,
                    m.due or utcmax,
                    embedded_numbers(m.name))
        mils.sort(key=milestone_order)
        for m in mils:
            StructuredMilestone._deep_sort(m.kids)
        return mils

    def __str__(self):
        return "StructuredMilestone<name='%s', kids='%s'>" % (self.name, self.kids)
        
    __repr__=__str__