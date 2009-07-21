from trac.db import Table, Column, Index, DatabaseManager
_sql = [
    """CREATE VIEW all_cal_events AS
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
         WHERE COALESCE(completed,0)<>0""",
         
    """INSERT INTO calendar (id, name, owner, type)
          VALUES(0, 'Project Milestones Calendar', 'System','S')"""
]
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
    
    
def do_upgrade(env, db, installed_version):
    upgrade_to_0_2_0(env, db, installed_version)
    return True
