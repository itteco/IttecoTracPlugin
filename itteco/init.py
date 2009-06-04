#Copyright (c) 2009 Itteco.com
#
#Permission is hereby granted, free of charge, to any person
#obtaining a copy of this software and associated documentation
#files (the "Software"), to deal in the Software without
#restriction, including without limitation the rights to use,
#copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the
#Software is furnished to do so, subject to the following
#conditions:
#
#The above copyright notice and this permission notice shall be
#included in all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
#EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
#OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
#NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
#HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
#WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
#OTHER DEALINGS IN THE SOFTWARE.

import pkg_resources
from trac.core import *
from trac.config import ListOption
from trac.env import IEnvironmentSetupParticipant
from trac.ticket.model import Type
from trac.web.chrome import ITemplateProvider

from itteco import __package__, __version__
from itteco.ticket.api import IMilestoneChangeListener
from itteco.utils.config import get_version, set_version, do_upgrade


class IttecoEvnSetup(Component):
    """ Initialise database and environment for itteco components """
    implements(IEnvironmentSetupParticipant,ITemplateProvider)
    
    milestone_levels = ListOption('itteco-roadmap-config', 'milestone_levels',[],
        doc="All possible levels of hierarhial milestones.")

    scope_element = ListOption('itteco-whiteboard-tickets-config', 'scope_element', ['story'],
        doc="All tickets in a whiteboard would be grouped accorging their tracibility to this type of ticket")

    excluded_element = ListOption('itteco-whiteboard-tickets-config', 'excluded_element', [],
        doc="List of the ticket types, which should be excluded from the whiteboard.")

    work_element = property(lambda self: self._get_work_elements())
    
    change_listeners = ExtensionPoint(IMilestoneChangeListener)
    
    def _get_work_elements(self):
        """ Returns ticket types that are taken into consideration 
        while counting milestone progress """        
        ignore_types = set(self.scope_element) \
            | set(self.excluded_element) 
        return [type.name for type in Type.select(self.env) if type.name not in ignore_types]

    # IEnvironmentSetupParticipant
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
