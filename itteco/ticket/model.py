from copy import copy
from datetime import datetime
from trac.resource import *
from trac.ticket.model import Ticket, Milestone
from trac.util.datefmt import utc, utcmax, to_timestamp
from trac.util.translation import _
from trac.util.compat import set, sorted
from trac.util import embedded_numbers, partition
from trac.wiki.model import WikiPage

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

class StructuredMilestone(Milestone):
    """The model for structured milestone."""
     
    def __init__(self, env, milestone=None, db=None):
        self.parent = self._old_parent = self._level = None
        self._kids = []
        self._kids_were_fetched= False
        super(StructuredMilestone, self).__init__(env, milestone, db)

    def _fetch(self, name, db=None):
        if not db:
            db = self.env.get_db_cnx()
        self._fetch_parent(name, db)
        super(StructuredMilestone, self)._fetch(name, db)

    def _fetch_parent(self, name, db):
        cursor = db.cursor()
        cursor.execute("SELECT ms.parent "
                       "FROM milestone m, milestone_struct ms WHERE m.name=ms.name AND m.name=%s", (name,))
        row = cursor.fetchone()
        self._old_parent = self.parent= row and row[0] or None
        
    def _get_kids(self):
        if not self._kids and not self._kids_were_fetched:
            db = self.env.get_db_cnx()
            cursor = db.cursor()
            cursor.execute("SELECT m.name "
                           "FROM milestone m, milestone_struct ms WHERE m.name=ms.name AND ms.parent=%s", (self.name,))
            self._kids = [StructuredMilestone(self.env, name) for name, in cursor]
            self._kids_were_fetched = True
        return self._kids

    def _set_kids(self, val):
        self._kids_were_fetched = True
        self._kids = val

    def _from_database_row(self, row):
        self._old_parent = self.parent = row[-1]
        super(StructuredMilestone, self)._from_database(row[0:-1])

    level = property(fget = lambda self: self._get_level(), fset = lambda self, val: self._set_level(val))
    can_be_closed = property(lambda self: self._can_be_closed())
    kids = property (lambda self: self._get_kids(), lambda self, val: self._set_kids(val))
    
    def _can_be_closed(self):
        if self.kids:
            for kid in self.kids:
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
        cursor.execute("DELETE FROM milestone_struct WHERE name=%s or parent=%s", (self.name, self.name))

        super(StructuredMilestone, self).delete(retarget_to, author, db)
        if handle_commit:
            db.commit()

    def insert(self, db=None):
        assert self.name, 'Cannot create milestone with no name'
        handle_commit = False
        if not db:
            db = self.env.get_db_cnx()
            handle_commit = True

        super(StructuredMilestone, self).insert(db)
        if self.parent:
            cursor = db.cursor()
            cursor.execute("INSERT INTO milestone_struct (name,parent) VALUES (%s,%s)", (self.name, self.parent))
        if handle_commit:
            db.commit()

    def update(self, db=None):
        assert self.name, 'Cannot update milestone with no name'
        handle_commit = False
        if not db:
            db = self.env.get_db_cnx()
            handle_commit = True
            
        _old_name = self._old_name
        super(StructuredMilestone, self).update(db)
        if self.name!=_old_name:
            cursor = db.cursor()
            cursor.execute("UPDATE milestone_struct SET name=%s WHERE name=%s", (self.name, _old_name))
            cursor.execute("UPDATE milestone_struct SET parent=%s WHERE parent=%s", (self.name, _old_name))
        self.env.log.debug("Setting parent: new='%s' old='%s'" % (self.parent, self._old_parent))
        if self.parent or self._old_parent and self.parent!=self._old_parent:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM milestone_struct WHERE name=%s and parent=%s", (self.name, self._old_parent))
            if cursor.fetchone():
                cursor.execute("UPDATE milestone_struct SET parent=%s WHERE name=%s and parent=%s", (self.parent, self.name, self._old_parent))
            else:
                cursor.execute("INSERT INTO milestone_struct VALUES (%s,%s)", (self.name, self.parent))
        self._old_parent = self.parent

        if handle_commit:
            db.commit()
    
    @staticmethod
    def select(env, include_completed=True, db=None):
        if not db:
            db = env.get_db_cnx()
        sql = "SELECT m.name,due,completed,description, ms.parent \
                   FROM milestone m LEFT OUTER JOIN milestone_struct ms ON m.name=ms.name "
        if not include_completed:
            sql += "WHERE COALESCE(completed,0)=0 "
        cursor = db.cursor()
        cursor.execute(sql)
        milestones = []
        for row in cursor:
            milestone = StructuredMilestone(env)
            milestone._from_database_row(row)
            milestones.append(milestone)
        return StructuredMilestone.reorganize(milestones)
           
    @staticmethod
    def reorganize(milestones):
        if not milestones:
            return milestones

        for milestone in milestones:
            milestone.kids = []
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