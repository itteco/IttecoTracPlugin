import pkg_resources
from trac.core import *
from trac.config import ListOption
from trac.env import IEnvironmentSetupParticipant
from trac.web.chrome import ITemplateProvider

from itteco import __package__, __version__
from itteco.utils.config import get_version, set_version, do_upgrade


class IttecoEvnSetup(Component):
    """ Initialise database and environment for itteco components """
    implements(IEnvironmentSetupParticipant,ITemplateProvider)
    
    milestone_levels = ListOption('itteco-roadmap-config', 'milestone_levels',[])
    #=============================================================================
    # IEnvironmentSetupParticipant
    #=============================================================================
    def environment_created(self):
        self.upgrade_environment(self.env.get_db_cnx())
    
    def environment_needs_upgrade(self, db):
        db_ver = get_version(db)
        return db_ver < [int(i) for i in __version__.split('.')]
    
    def upgrade_environment(self, db):
        db = db or self.env.get_db_cnx()
        do_upgrade(self.env, db, get_version(db))
        db.commit()
    
    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        return [(__package__, pkg_resources.resource_filename(__package__, 'htdocs'))]

    def get_templates_dirs(self):
        return [pkg_resources.resource_filename(__package__, 'templates')]
