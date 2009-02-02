from pkg_resources import resource_filename
import os
from trac.config import Configuration
from trac.db import Table, Column, Index, DatabaseManager
from itteco import __package__, __version__

def do_upgrade(env, db, version):
    if version>=[0,1,2]:
        return True
    trac_cfg = env.config['trac']
    mainnav = trac_cfg.getlist('mainnav',[])
    try:
        i = mainnav.index('whiteboard')
    except ValueError:
        try:
            i = mainnav.index('roadmap')
            mainnav.insert(i+1, 'whiteboard')
            trac_cfg.set('mainnav', ','.join(mainnav))
            env.config.save()
        except:        
            pass
   
    cfg = Configuration(resource_filename(__name__, 'sample.ini'))
    for section in cfg.sections():
        target_cfg = env.config[section]
        for option, value in cfg.options(section):
            target_cfg.set(option, value)

    custom = env.config['ticket-custom']
    if 'business_value' not in custom or custom.get('business_value')!='select':
        custom.set('business_value', 'select')
        custom.set('business_value.label', 'Business Value')
        custom.set('business_value.options','|100|200|300|500|800|1200|2000|3000')	
    if 'complexity' not in custom or custom.get('complexity')!='select':
        custom.set('complexity', 'select')
        custom.set('complexity.label', 'Complexity')
        custom.set('complexity.options', '|0|1|2|3|5|8|13|21|34|55|89|134')
    env.config.save()
    if version>=[0,1]:
        return True

    tables = [
        Table('milestone_struct', key =['name','parent'])[
            Column('name'),
            Column('parent')],
        Table('tkt_links', key=['src', 'dest'])[
            Column('src', type='integer'),
            Column('dest', type='integer')]]
    
    db = db or env.get_db_cnx()
    cursor = db.cursor()
    db_backend, _ = DatabaseManager(env)._get_connector()
    for table in tables:
        for stmt in db_backend.to_sql(table):
            cursor.execute(stmt)
    return True