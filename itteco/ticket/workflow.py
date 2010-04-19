from genshi.builder import tag

from trac.core import implements, Component
from trac.ticket.default_workflow import parse_workflow_config
from trac.util.translation import _

from itteco.ticket.api import IMilestoneActionController

def get_workflow_config(config):
    raw_actions = list(config.options('itteco-milestone-workflow'))
    return parse_workflow_config(raw_actions)
    
class ConfigurableMilestoneWorkflow(Component):
    """Milestone action controller which provides actions according to a
    workflow defined in the TracIni configuration file, inside the
    [milestone-workflow] section.
    
    Most of the copy copy-pasted from ConfigurableTicketWorkflow
    """
    implements(IMilestoneActionController)
    
    def __init__(self, *args, **kwargs):
        Component.__init__(self, *args, **kwargs)
        self.actions = get_workflow_config(self.config)
        if not '_reset' in self.actions:
            # Special action that gets enabled if the current status no longer
            # exists, as no other action can then change its state. (#5307)
            self.actions['_reset'] = {
                'default': 0,
                'name': 'reset',
                'newstate': 'new',
                'oldstates': [],  # Will not be invoked unless needed
                'operations': ['reset_workflow'],
                'permissions': []}
        self.log.debug('Workflow actions at initialization: %s\n' %
                       str(self.actions))

    #implements(ITicketActionController)
    
    # IMilestoneActionController methods
    def get_milestone_actions(self, req, milestone):
        """Returns a list of (weight, action) tuples that are valid for this
        request and this milestone."""
        # Get the list of actions that can be performed

        # Determine the current status of this milestone.  If this milestone is in
        # the process of being modified, we need to base our information on the
        # pre-modified state so that we don't try to do two (or more!) steps at
        # once and get really confused.
        status = milestone._old.get('status', milestone['status']) or 'new'

        allowed_actions = []
        for action_name, action_info in self.actions.items():
            oldstates = action_info['oldstates']
            if oldstates == ['*'] or status in oldstates:
                # This action is valid in this state.  Check permissions.
                allowed = 0
                required_perms = action_info['permissions']
                if required_perms:
                    for permission in required_perms:
                        if permission in req.perm(milestone.resource):
                            allowed = 1
                            break
                else:
                    allowed = 1
                if allowed:
                    allowed_actions.append((action_info['default'],
                                            action_name))
        if not (status in ['new', 'closed'] or \
                    status in self.get_all_status()) \
                and 'MILESTONE_ADMIN' in req.perm(milestone.resource):
            # State no longer exists - add a 'reset' action if admin.
            allowed_actions.append((0, '_reset'))
        return allowed_actions

    def get_all_status(self):
        """Return a list of all states described by the configuration.

        """
        all_status = set()
        for action_name, action_info in self.actions.items():
            all_status.update(action_info['oldstates'])
            all_status.add(action_info['newstate'])
        all_status.discard('*')
        return all_status
        
    def render_milestone_action_control(self, req, milestone, action):
        self.log.debug('render_milestone_action_control: action "%s"' % action)

        this_action = self.actions[action]
        status = this_action['newstate']        
        operations = this_action['operations']
        current_owner = milestone._old.get('owner', milestone['owner'] or '(none)')

        control = [] # default to nothing
        hints = []
        if 'reset_workflow' in operations:
            control.append(tag("from invalid state "))
            hints.append(_("Current state no longer exists"))
        if 'del_owner' in operations:
            hints.append(_("The milestone will be disowned"))
        if 'set_owner' in operations:
            id = 'action_%s_reassign_owner' % action
            selected_owner = req.args.get(id, req.authname)

            if this_action.has_key('set_owner'):
                owners = [x.strip() for x in
                          this_action['set_owner'].split(',')]
            elif self.config.getbool('ticket', 'restrict_owner'):
                perm = PermissionSystem(self.env)
                owners = perm.get_users_with_permission('MILESTONE_MODIFY')
                owners.sort()
            else:
                owners = None

            if owners == None:
                owner = req.args.get(id, req.authname)
                control.append(tag(['to ', tag.input(type='text', id=id,
                                                     name=id, value=owner)]))
                hints.append(_("The owner will change from %(current_owner)s",
                               current_owner=current_owner))
            elif len(owners) == 1:
                control.append(tag('to %s ' % owners[0]))
                if milestone['owner'] != owners[0]:
                    hints.append(_("The owner will change from "
                                   "%(current_owner)s to %(selected_owner)s",
                                   current_owner=current_owner,
                                   selected_owner=owners[0]))
            else:
                control.append(tag([_("to "), tag.select(
                    [tag.option(x, selected=(x == selected_owner or None))
                     for x in owners],
                    id=id, name=id)]))
                hints.append(_("The owner will change from %(current_owner)s",
                               current_owner=current_owner))
        if 'set_owner_to_self' in operations and \
                milestone._old.get('owner', milestone['owner']) != req.authname:
            hints.append(_("The owner will change from %(current_owner)s "
                           "to %(authname)s", current_owner=current_owner,
                           authname=req.authname))
        if 'set_resolution' in operations:
            if this_action.has_key('set_resolution'):
                resolutions = [x.strip() for x in
                               this_action['set_resolution'].split(',')]
            else:
                resolutions = [val.name for val in
                               model.Resolution.select(self.env)]
            if not resolutions:
                raise TracError(_("Your workflow attempts to set a resolution "
                                  "but none is defined (configuration issue, "
                                  "please contact your Trac admin)."))
            if len(resolutions) == 1:
                control.append(tag('as %s' % resolutions[0]))
                hints.append(_("The resolution will be set to %s") %
                             resolutions[0])
            else:
                id = 'action_%s_resolve_resolution' % action
                selected_option = req.args.get(id,
                        self.config.get('milestone', 'default_resolution'))
                control.append(tag(['as ', tag.select(
                    [tag.option(x, selected=(x == selected_option or None))
                     for x in resolutions],
                    id=id, name=id)]))
                hints.append(_("The resolution will be set"))
        if 'leave_status' in operations:
            control.append('as %s ' % milestone._old.get('status', 
                                                      milestone['status']))
        else:
            if status != '*':
                hints.append(_("Next status will be '%s'") % status)
        return (this_action['name'], tag(*control), '. '.join(hints))

    def get_milestone_changes(self, req, milestone, action):
        this_action = self.actions[action]

        # Enforce permissions
        if not self._has_perms_for_action(req, this_action, milestone.resource):
            # The user does not have any of the listed permissions, so we won't
            # do anything.
            return {}

        updated = {}
        # Status changes
        status = this_action['newstate']
        print status
        if status != '*':
            updated['status'] = status

        for operation in this_action['operations']:
            if operation == 'reset_workflow':
                updated['status'] = 'new'
            if operation == 'del_owner':
                updated['owner'] = ''
            elif operation == 'set_owner':
                newowner = req.args.get('action_%s_reassign_owner' % action,
                                    this_action.get('set_owner', '').strip())
                # If there was already an owner, we get a list, [new, old],
                # but if there wasn't we just get new.
                if type(newowner) == list:
                    newowner = newowner[0]
                updated['owner'] = newowner
            elif operation == 'set_owner_to_self':
                updated['owner'] = req.authname

            if operation == 'del_resolution':
                updated['resolution'] = ''
            elif operation == 'set_resolution':
                newresolution = req.args.get('action_%s_resolve_resolution' % \
                                             action,
                                this_action.get('set_resolution', '').strip())
                updated['resolution'] = newresolution

            # leave_status is just a no-op here, so we don't look for it.
        return updated

    def apply_action_side_effects(self, req, milestone, action):
        pass

    def _has_perms_for_action(self, req, action, resource):
        required_perms = action['permissions']
        if required_perms:
            for permission in required_perms:
                if permission in req.perm(resource):
                    break
            else:
                # The user does not have any of the listed permissions
                return False
        return True

    # Public methods (for other ITicketActionControllers that want to use
    #                 our config file and provide an operation for an action)
    
    def get_actions_by_operation(self, operation):
        """Return a list of all actions with a given operation
        (for use in the controller's get_all_status())
        """
        actions = [(info['default'], action) for action, info
                   in self.actions.items()
                   if operation in info['operations']]
        return actions

    def get_actions_by_operation_for_req(self, req, milestone, operation):
        """Return list of all actions with a given operation that are valid
        in the given state for the controller's get_milestone_actions().

        If state='*' (the default), all actions with the given operation are
        returned.
        """
        # Be sure to look at the original status.
        status = milestone._old.get('status', milestone['status'])
        actions = [(info['default'], action) for action, info
                   in self.actions.items()
                   if operation in info['operations'] and
                      ('*' in info['oldstates'] or
                       status in info['oldstates']) and
                      self._has_perms_for_action(req, info, milestone.resource)]
        return actions
