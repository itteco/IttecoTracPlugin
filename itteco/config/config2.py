from datetime import datetime
from trac.db import Table, Column, Index, DatabaseManager, get_column_names
from trac.util.datefmt import utc, to_timestamp

_view_sql = """
    CREATE VIEW all_cal_events AS
    SELECT ''||id as id, title as title, description as description, calendar_id as calendar_id,
           ticket as ticket, dtstart as dtstart, dtend as dtend,
           created as created, modified as modified
      FROM cal_event
    UNION
    SELECT name as id, name||'[Due]' as title, description as description , 0 as calendar_id, 
           null as ticket, due as dtstart, due+3600 as dtend,
           null as created, null as modified
      FROM milestone
     WHERE COALESCE(due,0)<>0
    UNION
    SELECT name as id, name||'[Completed]' as title, description as description , 0 as calendar_id, 
           null as ticket, completed as dtstart, completed+3600 as dtend,
           null as created, null as modified
      FROM milestone
     WHERE COALESCE(completed,0)<>0""";
         
_view_sql_0_2_2 = """
    CREATE VIEW all_cal_events AS
    SELECT ''||id as id, title as title, description as description, calendar_id as calendar_id,
           allday as allday,
           ticket as ticket, dtstart as dtstart, dtend as dtend,
           created as created, modified as modified
      FROM cal_event
    UNION
    SELECT name as id, name||'[Due]' as title, description as description , 0 as calendar_id,
           1 as allday,
           null as ticket, due as dtstart, due+3600 as dtend,
           null as created, null as modified
      FROM milestone
     WHERE COALESCE(due,0)<>0
    UNION
    SELECT name as id, name||'[Completed]' as title, description as description , 0 as calendar_id,
           1 as allday,
           null as ticket, completed as dtstart, completed+3600 as dtend,
           null as created, null as modified
      FROM milestone
     WHERE COALESCE(completed,0)<>0""";

_sql = [
    _view_sql,         
    """INSERT INTO calendar (id, name, owner, type)
          VALUES(0, 'Milestones', 'System','S')"""
]

_sql_0_2_2 = [
    "ALTER TABLE cal_event ADD COLUMN allday int",
    "UPDATE cal_event SET allday=0",
    "DROP VIEW all_cal_events",
    _view_sql_0_2_2
]    

_sql_0_2_3 = [
    "UPDATE calendar SET name='Milestones' WHERE id=0",
]
    
def do_upgrade(env, db, installed_version):
    upgrade_to_0_2_0(env, db, installed_version)
    upgrade_to_0_2_2(env, db, installed_version)
    upgrade_to_0_2_3(env, db, installed_version)
    upgrade_to_0_2_4(env, db, installed_version)
    upgrade_to_0_2_5(env, db, installed_version)
    upgrade_to_0_2_6(env, db, installed_version)
    return True

def upgrade_to_0_2_0(env, db, installed_version):
    if installed_version>=[0,2,0]:
        return True
    tables = [
        Table('calendar', key='id')[
            Column('id', auto_increment=True),
            Column('name'),
            Column('owner'),
            Column('type', size=1),
            Column('alias'),
            Column('theme', type='int'),
            Column('ref', type='int'),
            Column('created', type='int'),
            Column('modified', type='int'),
            Index(['alias'])],
        Table('cal_event', key='id')[
            Column('id', auto_increment=True),
            Column('title'),
            Column('description'),
            Column('calendar_id', type='int'),#calendar id
            Column('ticket', type='int'),#referenced ticket
            Column('dtstart', type='int'),
            Column('dtend', type='int'),
            Column('created', type='int'),
            Column('modified', type='int'),
            Index(['dtstart']),
            Index(['dtend'])],
        Table('time_track', key=('event_id', 'owner'))[
            Column('event_id'),
            Column('owner'),
            Column('auto', type='int'),
            Column('time', type='int'),
            Index(['owner'])]
    ]
    
    db = db or env.get_db_cnx()
    cursor = db.cursor()
    db_backend, _ = DatabaseManager(env)._get_connector()
    for table in tables:
        for stmt in db_backend.to_sql(table):
            cursor.execute(stmt)
    for stmt in _sql:
        cursor.execute(stmt)

    return True
    
def upgrade_to_0_2_2(env, db, installed_version):
    if installed_version>=[0,2,2]:
        return True

    db = db or env.get_db_cnx()
    cursor = db.cursor()
    for stmt in _sql_0_2_2:
        cursor.execute(stmt)
    
def upgrade_to_0_2_3(env, db, installed_version):
    if installed_version>=[0,2,3]:
        return True

    db = db or env.get_db_cnx()
    cursor = db.cursor()
    for stmt in _sql_0_2_3:
        cursor.execute(stmt)
    wb_cfg = env.config['itteco-whiteboard-config']
    if wb_cfg.get('burndown_info_povider'):
        wb_cfg.set('burndown_info_provider', wb_cfg.get('burndown_info_povider'))

    comp_config = env.config['components']
    comp_config.set('tracrpc.*', 'enabled')

    env.config.save()
    
def upgrade_to_0_2_4(env, db, installed_version):
    if installed_version>=[0,2,4]:
        return True

    milestones_shema_ext = [
        Table('milestone_change', key=('milestone', 'time', 'field'))[
            Column('milestone'),
            Column('time', type='int'),
            Column('author'),
            Column('field'),
            Column('oldvalue'),
            Column('newvalue'),
            Index(['milestone']),
            Index(['time'])],

        Table('milestone_custom', key=('milestone', 'name'))[
            Column('milestone'),
            Column('name'),
            Column('value')]
    ]

    db = db or env.get_db_cnx()
    cursor = db.cursor()
    db_backend, _ = DatabaseManager(env)._get_connector()
    for table in milestones_shema_ext:
        for stmt in db_backend.to_sql(table):
            cursor.execute(stmt)

    return True
    
def upgrade_to_0_2_5(env, db, installed_version):
    if installed_version>=[0,2,5]:
        return True
    db = db or env.get_db_cnx()
    cursor = db.cursor()
    now = to_timestamp(datetime.now(utc))
    cursor.execute("INSERT INTO ticket (type, status, summary, description, time, changetime) "
                       " SELECT '$milestone$', 'new', name, description, %s, %s"
                         " FROM milestone m"
                        " WHERE NOT EXISTS ("
                                " SELECT 1"
                                  " FROM ticket t" 
                                 " WHERE t.type='$milestone$'"
                                   " AND t.summary=m.name)", (now, now))
    cursor.execute("UPDATE ticket"
                     " SET status='finished'"
                   " WHERE status='new'"
                     " AND type='$milestone$'"
                     " AND EXISTS ("
                            " SELECT 1"
                              " FROM milestone m"
                             " WHERE summary=m.name"
                               " AND COALESCE(m.completed,0)<>0)")
    cursor.execute("SELECT * FROM milestone as tab LIMIT 1")
    col_names = get_column_names(cursor)
    if 'started' in col_names:
        cursor.execute("UPDATE ticket"
                         " SET status='started'"
                       " WHERE status='new'"
                         " AND type='$milestone$'"
                         " AND EXISTS ("
                                " SELECT 1"
                                  " FROM milestone m"
                                 " WHERE summary=m.name"
                                   " AND COALESCE(m.started,0)<>0)")
        cursor.execute("INSERT INTO ticket_custom (ticket, name, value)"
                        " SELECT t.id, 'started', m.started"
                          " FROM ticket t, milestone m"
                         " WHERE t.type='$milestone$'"
                           " AND t.summary=m.name"
                           " AND COALESCE(m.started,0)<>0")
                           
        cursor.execute("UPDATE ticket"
                         " SET milestone = (SELECT parent FROM milestone_struct WHERE name=summary)"
                       " WHERE type='$milestone$'")

    trac_cfg = env.config['trac']
    policies = trac_cfg.get('permission_policies') or ''
    for policy in ('CalendarSystem', 'HideMilestoneTicketPolicy'):
        if policies:
            policies = ','.join([policy, policies])
        else:
            policies = policy
    trac_cfg.set('permission_policies', policies)
    env.config.save()
    
def upgrade_to_0_2_6(env, db, installed_version):
    if installed_version>=[0,2,6]:
        return True
        
    cfg = env.config['itteco-whiteboard-tickets-config']
    defaults = cfg.get('default_fields')
    if defaults:
        defaults = [name.strip() for name in defaults.split(',')]
        try:
            idx = defaults.index('description')
            defaults.insert(idx+1, 'milestone')
        except ValueError:
            defaults.append('milestone')
        cfg.set('default_fields', ','.join(defaults))
        env.config.save()
