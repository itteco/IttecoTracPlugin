import trac.perm as perm
from itteco.init import IttecoEvnSetup
from itteco.utils.config import do_upgrade
from itteco.calendar.api import CalendarSystem
from itteco.calendar.rpc import CalendarRPC
from itteco.calendar.model import Calendar, CalendarType
from trac.test import EnvironmentStub, Mock

import unittest


class CalendarRPCTestCase(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(enable=['trac.*', 'itteco.*'])
        self.env.config.set('trac', 'permission_policies', 'CalendarSystem, DefaultPermissionPolicy')
        
        self.itteco_env= IttecoEvnSetup(self.env)
        self.itteco_env.upgrade_environment(self.env.get_db_cnx())
        
        #self.calendar_system = CalendarSystem(self.env)
        self.rpc = CalendarRPC(self.env)
        self.perm_system = perm.PermissionSystem(self.env)        
        self.req = Mock()
        self.req.perm = perm.PermissionCache(self.env, 'testuser')
        self._createTestData();


    def tearDown(self):
        self.env.reset_db()

    def _createTestData(self):
        self._create_calendar('cal1', 'testuser')
        self._create_calendar('cal2', 'testuser')
        self._create_calendar('cal3', 'user1')
        self._create_calendar('cal4', 'user1', CalendarType.Shared)
        
    def _create_calendar(self, name, username, type= CalendarType.Private):
        calendar = Calendar(self.env, None, username)
        calendar.name = name
        calendar.theme = 1
        calendar.type = type
        id = calendar.insert()
        return calendar
        

    def test_calendars_rpc(self):
        self.assertEqual('calendar', self.rpc.xmlrpc_namespace())
        self.assertEqual(['cal1','cal2','cal4'], [c.name for c in self.rpc.query(self.req)])
        
def suite():
    return unittest.makeSuite(CalendarRPCTestCase, 'test')

if __name__=='__main__':
    unittest.main()
