from ConfigParser import ConfigParser
from pkg_resources import resource_filename
import os
from trac.config import Configuration
from trac.db import Table, Column, Index, DatabaseManager
from trac.db_default import schema

from itteco import __version__

def do_upgrade(env, db, installed_version):
    env.log.debug("Upgrading from version %s" % installed_version)
    do_initial_setup(env, db, installed_version)
    upgrade_to_0_1_2(env, db, installed_version)
    upgrade_to_0_1_9(env, db, installed_version)
    upgrade_to_0_1_10(env, db, installed_version)
    
    return True

def do_initial_setup(env, db, installed_version):
    if installed_version>=[0,1]:
        return

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
    env.log.debug("Upgrading: do_initial_setup")

def upgrade_to_0_1_2(env, db, installed_version):
    if installed_version>=[0,1,2]:
        return

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
    available_sections = [s for s in env.config.sections()]
    cfg = ConfigParser()
    cfg.read(resource_filename(__name__, 'sample.ini'))
    for section in cfg.sections():
        if section[:6]!='itteco' or section not in available_sections:
            target_cfg = env.config[section]
            for option in cfg.options(section):
                target_cfg.set(option, cfg.get(section, option))

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
    env.log.debug("Upgrading: upgrade_to_0_1_2")
    
def upgrade_to_0_1_9(env, db, installed_version):
    if installed_version>=[0,1,9]:
        return
        
    cursor = db.cursor()
    mil_table = None
    for table in schema:
        if table.name =='milestone':
            mil_table = table
            break
    
    if mil_table:
        cols ="," .join([c.name for c in mil_table.columns])
        cursor.execute("CREATE TEMPORARY TABLE milestone_old as SELECT %s FROM milestone;" % cols)
        cursor.execute("DROP TABLE milestone;")

        new_mil_table = Table('milestone', key='id')[
            mil_table.columns+mil_table.indices+[Column('started', type='int')]]

        db_backend, _ = DatabaseManager(env)._get_connector()
        for stmt in db_backend.to_sql(new_mil_table):
            cursor.execute(stmt)
        cursor.execute("INSERT INTO milestone (%s) SELECT %s FROM milestone_old;" % (cols, cols))
    env.log.debug("Upgrading: upgrade_to_0_1_9")
    
def upgrade_to_0_1_10(env, db, installed_version):
    if installed_version>=[0,1,10]:
        return
        
    groups_config = env.config['itteco-whiteboard-groups']
    groups_config.set('use_workflow_configuration', 'true')
    env.config.save()
    env.log.debug("Upgrading: upgrade_to_0_1_10")

