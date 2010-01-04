from trac.core import Component, implements
from trac.perm import IPermissionPolicy, IPermissionRequestor

from itteco.calendar.model import CalendarType, Calendar

class CalendarSystem(Component):
    """ Calendars management system. """
    implements(IPermissionRequestor, IPermissionPolicy)
    
    # IPermissionRequestor methods
    def get_permission_actions(self):
        return ['CALENDAR_CREATE', 'CALENDAR_VIEW',
                'CALENDAR_MODIFY', 'CALENDAR_DELETE',
                ('CALENDAR_ADMIN', ['CALENDAR_CREATE', 'CALENDAR_VIEW',
                                    'CALENDAR_MODIFY', 'CALENDAR_DELETE'])]

    def check_permission(self, action, username, resource, perm):
        if action not in ['CALENDAR_VIEW', 'CALENDAR_MODIFY', 'CALENDAR_DELETE'] \
            or not resource or resource.realm !='calendar' or resource.id is None:
            
            return
        
        if 'CALENDAR_ADMIN' in perm:
            return True
        calObject = Calendar(self.env, resource.id)
        return calObject.exists and (calObject.owner==username or \
                                     ('CALENDAR_VIEW'==action and calObject.type==CalendarType.Shared))
