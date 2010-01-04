import trac.perm as perm
from itteco.init import IttecoEvnSetup
from itteco.utils.config import do_upgrade
from itteco.calendar.api import CalendarSystem
from itteco.calendar.model import Calendar, CalendarType
from trac.test import EnvironmentStub, Mock

import unittest


class CalendarSystemTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'itteco.*'])
        self.env.config.set('trac', 'permission_policies', 'CalendarSystem, DefaultPermissionPolicy')
        
        self.itteco_env= IttecoEvnSetup(self.env)
        self.itteco_env.upgrade_environment(self.env.get_db_cnx())
        
        self.calendar_system = CalendarSystem(self.env)
        self.perm_system = perm.PermissionSystem(self.env)
        
        self.perm = perm.PermissionCache(self.env, 'testuser')

    def tearDown(self):
        self.env.reset_db()

    def _create_calendar(self, name, username, type= CalendarType.Private):
        calendar = Calendar(self.env, None, username)
        calendar.theme = 1
        calendar.type = type
        id = calendar.insert()
        return calendar
        

    def test_permission_policies(self):
        self.perm_system.grant_permission('testuser', 'CALENDAR_CREATE')
        self.perm_system.grant_permission('testuser', 'CALENDAR_MODIFY')
        self.perm_system.grant_permission('testuser', 'CALENDAR_VIEW')
        self.perm_system.grant_permission('testuser', 'CALENDAR_DELETE')

        self.assertTrue('CALENDAR_CREATE' in self.perm)
        
        calendar = self._create_calendar('cal1', 'testuser')        
        c = calendar.resource
        
        self.assertTrue('CALENDAR_MODIFY' in self.perm(c))
        self.assertTrue('CALENDAR_VIEW' in self.perm(c))
        self.assertTrue('CALENDAR_DELETE' in self.perm(c))

        calendar2 = self._create_calendar('cal2', 'user1')
        c2 = calendar2.resource

        self.assertTrue('CALENDAR_VIEW' not in self.perm(c2), \
            'There should be no access to private calendar of another user.')

        calendar3 = self._create_calendar('cal3', 'user1', CalendarType.Shared)        
        c3 = calendar3.resource

        self.assertTrue('CALENDAR_VIEW' in self.perm(c3), \
            'There should view access to shared calendars.')
        
def suite():
    return unittest.makeSuite(CalendarSystemTestCase, 'test')

if __name__=='__main__':
    unittest.main()
