from datetime import datetime
from trac.core import TracError
from trac.config import ListOption
from trac.resource import ResourceNotFound
from trac.ticket.admin import MilestoneAdminPanel
from trac.util.datefmt import utc, parse_date, get_date_format_hint, \
                              get_datetime_format_hint
from trac.util.translation import _

from itteco.init import IttecoEvnSetup
from itteco.ticket.model import StructuredMilestone
from itteco.utils.render import get_powered_by_sign, add_jscript

from trac.web.chrome import add_link, add_script,add_stylesheet

class IttecoMilestoneAdminPanel(MilestoneAdminPanel):
    milestone_levels = ListOption('itteco-roadmap-config', 'milestone_levels', [])

    def _render_admin_panel(self, req, cat, page, milestone):
        req.perm.require('TICKET_ADMIN')
        add_stylesheet(req, 'itteco/css/common.css')
        add_jscript(
            req, 
            [
                'stuff/ui/ui.core.js',
                'stuff/ui/ui.resizable.js',
                'custom_select.js'
            ],
            IttecoEvnSetup(self.env).debug
        )
        # Detail view?
        if milestone:
            mil = StructuredMilestone(self.env, milestone)
            if req.method == 'POST':
                if req.args.get('save'):
                    mil.name = req.args.get('name')
                    mil.due = mil.completed = None
                    due = req.args.get('duedate', '')
                    if due:
                        mil.due = parse_date(due, req.tz)
                    if req.args.get('completed', False):
                        completed = req.args.get('completeddate', '')
                        mil.completed = parse_date(completed, req.tz)
                        if mil.completed > datetime.now(utc):
                            raise TracError(_('Completion date may not be in '
                                              'the future'),
                                            _('Invalid Completion Date'))
                    mil.description = req.args.get('description', '')
                    mil.parent = req.args.get('parent', None)
                    if mil.parent and mil.parent==mil.name:
                        raise TracError(_('Milestone cannot be parent for itself,Please, give it another thought.'),
                                        _('Something is wrong with Parent Milestone. Will you check it please?'))

                    if mil.parent and not StructuredMilestone(self.env, mil.parent).exists:
                        raise TracError(_('Milestone should have a valid parent. It does not look like this is the case.'),
                                        _('Something is wrong with Parent Milestone. Will you check it please?'))
                    mil.update()
                    req.redirect(req.href.admin(cat, page))
                elif req.args.get('cancel'):
                    req.redirect(req.href.admin(cat, page))

            add_script(req, 'common/js/wikitoolbar.js')
            data = {'view': 'detail', 'milestone': mil}

        else:
            if req.method == 'POST':
                # Add Milestone
                if req.args.get('add') and req.args.get('name'):
                    name = req.args.get('name')
                    try:
                        StructuredMilestone(self.env, name)
                    except ResourceNotFound:
                        mil = StructuredMilestone(self.env)
                        mil.name = name
                        if req.args.get('duedate'):
                            mil.due = parse_date(req.args.get('duedate'),
                                                 req.tz)
                        mil.parent = req.args.get('parent', None)
                        if mil.parent and not StructuredMilestone(self.env, mil.parent).exists:
                            raise TracError(_('Milestone should have a valid parent. It does not look like this is the case'),
                                            _('Something is wrong with Parent Milestone. Will you check it please?'))

                        mil.insert()
                        req.redirect(req.href.admin(cat, page))
                    else:
                        raise TracError(_('Sorry, milestone %s already exists.') % name)

                # Remove milestone
                elif req.args.get('remove'):
                    sel = req.args.get('sel')
                    if not sel:
                        raise TracError(_('Please, select the milestone.'))
                    if not isinstance(sel, list):
                        sel = [sel]
                    db = self.env.get_db_cnx()
                    for name in sel:
                        mil = StructuredMilestone(self.env, name, db=db)
                        mil.delete(db=db)
                    db.commit()
                    req.redirect(req.href.admin(cat, page))

                # Set default milestone
                elif req.args.get('apply'):
                    if req.args.get('default'):
                        name = req.args.get('default')
                        self.config.set('ticket', 'default_milestone', name)
                        self.config.save()
                        req.redirect(req.href.admin(cat, page))

            data = {
                'view': 'list',
                'default': self.config.get('ticket', 'default_milestone'),
            }
            
        # Get ticket count
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        milestones = []
        structured_milestones = StructuredMilestone.select(self.env)
        mil_names = self._get_mil_names(structured_milestones)
        
        cursor.execute("SELECT milestone, COUNT(*) FROM ticket "
                   "WHERE milestone IN (%s) GROUP BY milestone" % ("%s,"*len(mil_names))[:-1], mil_names)
        mil_tkt_quantity = {}
        for mil, cnt in cursor:
            mil_tkt_quantity[mil]=cnt

        data.update({
            'date_hint': get_date_format_hint(),
            'milestones': [(mil, 0) for mil in structured_milestones],# we recover this anyway
            'structured_milestones': structured_milestones,
            'milestone_tickets_quantity': mil_tkt_quantity,
            'max_milestone_level': self.milestone_levels and len(self.milestone_levels)-1 or 0,
            'datetime_hint': get_datetime_format_hint()
        })
        return 'itteco_admin_milestones.html', data
        
    def _get_mil_names(self, mils):
        res = []
        if mils:
            for mil in mils:
                res.append(mil.name)
                res.extend(self._get_mil_names(mil.kids))
        return res