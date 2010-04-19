from trac.core import TracError
from itteco import __package__, __version__

__select_sql = "SELECT value FROM system WHERE name=%s"
__insert_sql = "INSERT INTO system (name, value) VALUES (%s, %s)"
__update_sql = "UPDATE system SET value=%s WHERE name=%s"

def do_upgrade(env, db, version, pkg=__package__, new_version=__version__):
    completed = True
    i = 1
    while completed:
        try:
            script_path = '%s.config.config%i' % (pkg, i)
            module = __import__(script_path, globals(), locals(), ['do_upgrade'])
            completed = completed and module.do_upgrade(env, db, version)
            i +=1
        except ImportError:
            break
    if completed:
        set_version(db, pkg, new_version)
    else:
        raise TracError("[%s]: Upgrade was not complete! Check log for details..." % __package__)

def get_version(db, pkg=__package__):
    cursor = db.cursor()
    cursor.execute(__select_sql, (pkg,))
    row = cursor.fetchone()
    if row and len(row) > 0:
        return [int(i) for i in row[0].split('.')]
    return [0]

def set_version(db, pkg, version):
    try:
        cursor = db.cursor()
        cursor.execute(__select_sql, (pkg,))
        if cursor.fetchone():
            cursor.execute(__update_sql, (version, pkg))
        else:
            cursor.execute(__insert_sql, (pkg, version))
    except Exception, e:
        raise TracError("[%s]: failed to set version [%s]" % (pkg, str(e)))
