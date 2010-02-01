import re
try:
    import threading
except ImportError:
    import dummy_threading as threading

from trac.core import implements, Interface, Component
from trac.config import OrderedExtensionsOption, IntOption

class IMilestoneActionController(Interface):
    """Extension point interface for components willing to participate
    in the milestone workflow.

    This is mainly about controlling the changes to the milestone ''status'',
    though not restricted to it.
    """

    def get_milestone_actions(req, milestone):
        """Return an iterable of `(weight, action)` tuples corresponding to
        the actions that are contributed by this component.
        That list may vary given the current state of the milestone and the
        actual request parameter.

        `action` is a key used to identify that particular action.
        (note that 'history' and 'diff' are reserved and should not be used
        by plugins)
        
        The actions will be presented on the page in descending order of the
        integer weight. The first action in the list is used as the default
        action.

        When in doubt, use a weight of 0."""

    def get_all_status():
        """Returns an iterable of all the possible values for the ''status''
        field this action controller knows about.

        This will be used to populate the query options and the like.
        It is assumed that the initial status of a milestone is 'new' and
        the terminal status of a milestone is 'closed'.
        """

    def render_milestone_action_control(req, milestone, action):
        """Return a tuple in the form of `(label, control, hint)`

        `label` is a short text that will be used when listing the action,
        `control` is the markup for the action control and `hint` should
        explain what will happen if this action is taken.
        
        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_milestone_actions`.

        Note that the radio button for the action has an `id` of
        `"action_%s" % action`.  Any `id`s used in `control` need to be made
        unique.  The method used in the default IMilestoneActionController is to
        use `"action_%s_something" % action`.
        """

    def get_milestone_changes(req, milestone, action):
        """Return a dictionary of milestone field changes.

        This method must not have any side-effects because it will also
        be called in preview mode (`req.args['preview']` will be set, then).
        See `apply_action_side_effects` for that. If the latter indeed triggers
        some side-effects, it is advised to emit a warning
        (`trac.web.chrome.add_warning(req, reason)`) when this method is called
        in preview mode.

        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_milestone_actions`.
        """

    def apply_action_side_effects(req, milestone, action):
        """Perform side effects once all changes have been made to the milestone.

        Multiple controllers might be involved, so the apply side-effects
        offers a chance to trigger a side-effect based on the given `action`
        after the new state of the milestone has been saved.

        This method will only be called if the controller claimed to handle
        the given `action` in the call to `get_milestone_actions`.
        """

class IMilestoneChangeListener(Interface):
    """Extension point interface for components that require notification
    when milestones are created, modified, or deleted."""

    def milestone_created(milestone):
        """Called when a milestone is created."""

    def milestone_changed(milestone, old_values):
        """Called when a milestone is modified.
        
        `old_values` is a dictionary containing the previous values of the
        fields that have changed.
        """

    def milestone_deleted(milestone):
        """Called when a milestone is deleted."""
        
class MilestoneSystem(Component):
    """
    Copy of the TicketSystem for enabling the same functionality for milestones.
    """
    action_controllers = OrderedExtensionsOption('itteco-milestone', 'workflow',
        IMilestoneActionController, default='ConfigurableMilestoneWorkflow',
        include_missing=False,
        doc="""Ordered list of workflow controllers to use for milestone actions.""")

    tickets_report = IntOption('itteco-milestone', 'tickets_report',
        doc="""Ordered list of workflow controllers to use for milestone actions.""")
        
    _fields = None
    _custom_fields = None
    
    def __init__(self):
        self.log.debug('action controllers for milestone workflow: %r' % 
                [c.__class__.__name__ for c in self.action_controllers])
        self._fields_lock = threading.RLock()

    # Public API

    def get_available_actions(self, req, milestone):
        """Returns a sorted list of available actions"""
        # The list should not have duplicates.
        actions = {}
        for controller in self.action_controllers:
            weighted_actions = controller.get_milestone_actions(req, milestone)
            for weight, action in weighted_actions:
                if action in actions:
                    actions[action] = max(actions[action], weight)
                else:
                    actions[action] = weight
        all_weighted_actions = [(weight, action) for action, weight in
                                actions.items()]
        return [x[1] for x in sorted(all_weighted_actions, reverse=True)]

    def get_all_status(self):
        """Returns a sorted list of all the states all of the action
        controllers know about."""
        valid_states = set()
        for controller in self.action_controllers:
            valid_states.update(controller.get_all_status())
        return sorted(valid_states)

    def get_milestone_fields(self):
        """Returns the list of fields available for milestones."""
        # This is now cached - as it makes quite a number of things faster,
        # e.g. #6436
        if self._fields is None:
            self._fields_lock.acquire()
            try:
                if self._fields is None: # double-check (race after 1st check)
                    self._fields = self._get_milestone_fields()
            finally:
                self._fields_lock.release()
        return [f.copy() for f in self._fields]

    def reset_milestone_fields(self):
        self._fields_lock.acquire()
        try:
            self._fields = None
            self.config.touch() # brute force approach for now
        finally:
            self._fields_lock.release()

    def _get_milestone_fields(self):

        db = self.env.get_db_cnx()
        fields = [
            {'name' : 'started', 'type' : 'text', 'label' : 'Started At', 'hidden' : True},
            {'name' : 'parent',  'type' : 'text', 'label' : 'Parent', 'hidden' : True},
            {'name' : 'owner',  'type' : 'text', 'label' : 'Owner', 'hidden' : True},
            {
                'name'   : 'status',  
                'type'   : 'select', 
                'label'  : 'Status',
                'options': MilestoneSystem(self.env).get_all_status(),
                'hidden' : True
            }
        ]
        #put the default fields is any
        
        for field in self.get_custom_fields():
            if field['name'] in [f['name'] for f in fields]:
                self.log.warning('Duplicate field name "%s" (ignoring)',
                                 field['name'])
                continue
            if field['name'] in self.reserved_field_names:
                self.log.warning('Field name "%s" is a reserved name '
                                 '(ignoring)', field['name'])
                continue
            if not re.match('^[a-zA-Z][a-zA-Z0-9_]+$', field['name']):
                self.log.warning('Invalid name for custom field: "%s" '
                                 '(ignoring)', field['name'])
                continue
            fields.append(field)

        return fields

    reserved_field_names = ['report', 'order', 'desc', 'group', 'groupdesc',
                            'col', 'row', 'format', 'max', 'page', 'verbose',
                            'comment']

    def get_custom_fields(self):
        if self._custom_fields is None:
            self._fields_lock.acquire()
            try:
                if self._custom_fields is None: # double-check
                    self._custom_fields = self._get_custom_fields()
            finally:
                self._fields_lock.release()
        return [f.copy() for f in self._custom_fields]

    def _get_custom_fields(self):
        fields = []
        config = self.config['milestone-custom']
        for name in [option for option, value in config.options()
                     if '.' not in option]:
            field = {
                'name': name,
                'type': config.get(name),
                'order': config.getint(name + '.order', 0),
                'label': config.get(name + '.label') or name.capitalize(),
                'value': config.get(name + '.value', '')
            }
            if field['type'] == 'select' or field['type'] == 'radio':
                field['options'] = config.getlist(name + '.options', sep='|')
                if '' in field['options']:
                    field['optional'] = True
                    field['options'].remove('')
            elif field['type'] == 'text':
                field['format'] = config.get(name + '.format', 'plain')
            elif field['type'] == 'textarea':
                field['format'] = config.get(name + '.format', 'plain')
                field['width'] = config.getint(name + '.cols')
                field['height'] = config.getint(name + '.rows')
            fields.append(field)

        fields.sort(lambda x, y: cmp(x['order'], y['order']))
        return fields


