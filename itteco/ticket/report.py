from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.core import implements, Component
from trac.ticket.model import Ticket
from trac.ticket.report import ReportModule
from trac.util.translation import _
from trac.web.api import ITemplateStreamFilter, IRequestFilter

from itteco.utils import json

class IttecoReportModule(Component):
    implements(ITemplateStreamFilter, IRequestFilter)
    
    mandatory_cols = ["__group__", "__group_preset__"]
    
    #ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        if filename=='report_view.html':
            self.env.log.debug("report data='%s'" % (data,))
            id = req.args.get('id')
            action = req.args.get('action', 'view')
            header_groups = data.get('header_groups')

            if id and action=='view' and header_groups and len(header_groups)>0:
                try:
                    if self._are_all_mandatory_fields_found(header_groups[0]):
                        link_builder = req.href.chrome
                        script_tag = lambda x: tag.script(type="text/javascript", src=link_builder(x))
                        stream |= Transformer("//head").append(tag(
                            # TODO fix scripts base path
                            tag.link(type="text/css", rel="stylesheet", href=link_builder("itteco/css/report.css")),
                            script_tag("itteco/js/jquery.ui/ui.core.js"),
                            script_tag("itteco/js/jquery.ui/ui.draggable.js"),
                            script_tag("itteco/js/jquery.ui/ui.droppable.js"),
                            script_tag("itteco/js/jquery.ui/ui.resizable.js"),
                            script_tag("itteco/js/report.js")))
                            
                        args = ReportModule(self.env).get_var_args(req)
                        db = self.env.get_db_cnx()
                        cursor = db.cursor()
                        cursor.execute("SELECT query FROM report WHERE id=%s", (id,))
                        sql, = cursor.fetchone()
                        sql, args = ReportModule(self.env).sql_sub_vars(sql, args, db)
                        cursor.execute("SELECT DISTINCT __group__, __group_preset__, count(*) "+\
                            "FROM (%s) as group_config GROUP BY  __group__, __group_preset__" % sql, args)
                        tags = []
                        for group, preset, quantity in cursor:
                            if preset:
                                tags.append(tag.div(group+'\n', \
                                    tag.span(
                                        quantity and '(%d match%s)' % (quantity, quantity!=1 and 'es' or '') \
                                            or '(No matches)', class_='numrows'), \
                                    preset=preset, class_='report-result'))
                        stream |= Transformer("//*[@id='main']").after(
                            tag.div(_render_conrol_panel(), tag.div(class_='content', *tags), id="dropbox"))
                except ValueError,e:
                    #we do not fail the report it self, may be it works in read only mode
                    self.env.log.debug('Report decoration failed: %s' % e)
        return stream

    def _are_all_mandatory_fields_found(self, cols):        
        found_fields = [col for col in cols if col['col'] in self.mandatory_cols]
        return len(found_fields)==len(self.mandatory_cols)

    #IRequestFilter methods
    def pre_process_request(self, req, handler):
        if req.path_info.startswith('/report/') and req.args.get('action')=='execute':
            return self
        return handler

    def post_process_request(self, req, template, content_type):
        return (template, content_type)

    def post_process_request(self, req, template, data, content_type):
        return (template, data, content_type)
        
    #IRequestHandler mathod for action processing
    def process_request(self, req):
        tickets = req.args.get('tickets','').split(',')
        presets = [kw.split('=', 1) for kw in req.args.get('presets','').split('&')]
        warn = []
        modified_tickets = []
        if tickets and presets:
            db = self.env.get_db_cnx()
            for ticket_id in tickets:
                if 'TICKET_CHGPROP' in req.perm('ticket', ticket_id):
                    ticket  = Ticket(self.env, ticket_id, db)
                    for preset in presets:
                        field = value = None
                        if len(preset)==2:
                            field, value = preset
                        else:
                            field, = preset
                        ticket[field] = value
                    ticket.save_changes(req.authname, _("Changed from executable report"), db=db)
                    modified_tickets.append(ticket_id)
                else:
                    warn.append(_("You have no permission to modify ticket '%(ticket)s'", ticket=ticket_id))
            db.commit()
        req.write(json.write({'tickets':modified_tickets, 'warnings': warn}))

def _render_conrol_panel():
    return tag.div(
      tag.span(
        tag.a(' ', class_='link-expanded', href='#'),
        tag.a(_('Collapse Control Panel'), href='#')),
      tag.span(
        tag.a(' ',class_='link-collapsed', href='#'),
        tag.a(_('Expand Control Panel'), href='#'),
        style="display: none;"),
      class_='control-panel'
    )