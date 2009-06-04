from trac.core import Interface


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

