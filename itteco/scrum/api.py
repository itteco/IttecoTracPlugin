from trac.config import ListOption
from trac.core import Interface, Component, implements

class ITeamMembersProvider(Interface):
    """Extension point interface for components that 
    provide team members for whiteboard."""
    def get_team_members():
        """ Return IDs of all team members"""

class ConfigBasedTeamMembersProvider(Component):
    implements(ITeamMembersProvider)

    team = ListOption('itteco-whiteboard-config', 'team',[],
        doc="The comma separated list of the team members. Is used on whiteboard.")

    def get_team_members(self):
        return self.team

class UserManagerPluginTeamMembersProvider(Component):
    implements(ITeamMembersProvider)

    def get_team_members(self):
        sql = "SELECT sid FROM session_attribute WHERE authenticated=1 and name='enabled' and value='1'"
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute(sql)
        return [sid for sid in cursor]

