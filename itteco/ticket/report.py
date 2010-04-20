from genshi.builder import tag
from genshi.filters.transform import Transformer

try:
    import threading
except ImportError:
    import dummy_threading as threading

from trac.config import ListOption
from trac.core import implements, Component
from trac.ticket.api import TicketSystem
from trac.ticket.model import Ticket
from trac.ticket.report import ReportModule
from trac.resource import Resource

from trac.util.translation import _
from trac.web.api import ITemplateStreamFilter, IRequestFilter

from itteco.init import IttecoEvnSetup
from itteco.utils import json
from itteco.utils.render import map_script

class IttecoReportModule(Component):
    implements(ITemplateStreamFilter, IRequestFilter)
    
    mandatory_cols = ["__group__", "__group_preset__"]
    
    main_reports = ListOption('itteco-report', 'main_reports','',
        doc="Comma separated list of ids of main reports.")
        
    id_cols = ['ticket', 'id', '_id']
    _config = None
    
    def __init__(self):
        self._config_lock = threading.RLock()
    
    #ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        if req.path_info.startswith('/report/'):
            link_builder = req.href.chrome
            debug = IttecoEvnSetup(self.env).debug
            def script_tag(path=None, content=None):
                kw = { 'type' : "text/javascript"}
                if path:
                    kw['src'] = link_builder(map_script(path, debug))
                return tag.script(content , **kw)

            stream |= Transformer("//head").prepend(
                        tag.link(type="text/css", rel="stylesheet", href=link_builder("itteco/css/report.css"))
                ).append(
                    tag(
                        script_tag('stuff/plugins/jquery.rpc.js'),
                        script_tag('stuff/ui/plugins/jquery.jeditable.js'),
                        script_tag("editable_report.js"),
                        script_tag(
                            content=
                            "$(document).ready(function(){"+
                                "$('#main').editableReport("+
                                    "{"+
                                        "rpcurl: '"+req.href('login','xmlrpc')+"',"+
                                        "fields: "+self.fields_dict(data.get('header_groups',[]))+"})"+
                            "});"
                        )
                    )
                )
            try:
                stream |= Transformer("//head").prepend(
                        tag(
                            # TODO fix scripts base path
                            tag.link(type="text/css", rel="stylesheet", href=link_builder("itteco/css/common.css")),
                            tag.link(type="text/css", rel="stylesheet", href=link_builder("itteco/css/report.css")),
                            #tag.link(type="text/css", rel="stylesheet", href=link_builder("itteco/css/colorbox/colorbox.css"))
                        )
                    ).append(
                        tag(
                            script_tag("stuff/ui/ui.core.js"),
                            script_tag("stuff/ui/ui.draggable.js"),
                            script_tag("stuff/ui/ui.droppable.js"),
                            script_tag("stuff/ui/ui.resizable.js"),
                            script_tag('stuff/ui/plugins/jquery.colorbox.js'),
                            script_tag('custom_select.js')
                        )
                    )
            except ValueError,e:
                #we do not fail the report it self, may be it works in read only mode
                self.env.log.debug('Report decoration failed: %s' % e)
        return stream

    def _are_all_mandatory_fields_found(self, cols):
        found_fields = [col for col in cols if col in self.mandatory_cols]
        id_cols = [col for col in cols if col in self.id_cols]
        return len(found_fields)==len(self.mandatory_cols) and len(id_cols)>0

    #IRequestFilter methods
    def pre_process_request(self, req, handler):
        if req.path_info.startswith('/report'):
            action = req.args.get('action', 'view')
            id = int(req.args.get('id','-1'))
            if action=='view' and id==-1:
                req.redirect(req.href.report(self.resolve_report_number(req)))
                
        return handler

    def post_process_request(self, req, template, content_type):
        return (template, content_type)

    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/report'):
            data['main_reports'] = [int(id) for id in self.main_reports]
            data['available_reports'] = self.available_reports(req)
        if data and data.get('row_groups'):
            id = req.args.get('id')
            action = req.args.get('action', 'view')
            header_groups = data.get('header_groups')
            row_groups= data.get('row_groups')

            if id and action=='view':
                req.session['last_used_report'] = id
                if header_groups and len(header_groups)>0:
                    all_col_names = [col['col'] for header_group in header_groups for col in header_group]
                    data['column_classes'] = dict(
                        [ (key, value.get('classname')) \
                            for key, value in self.fields_config().items() \
                                if key in all_col_names])
                    if self._are_all_mandatory_fields_found(all_col_names):
                        id_col = all_col_names[0]

                        args = ReportModule(self.env).get_var_args(req)
                        db = self.env.get_db_cnx()
                        cursor = db.cursor()
                        cursor.execute("SELECT query FROM report WHERE id=%s", (id,))
                        sql, = cursor.fetchone()
                        sql, args = ReportModule(self.env).sql_sub_vars(sql, args, db)
                        cursor.execute("SELECT DISTINCT __group__, __group_preset__, count("+id_col+") as q, count(*) as fq "+\
                            "FROM (%s) as group_config GROUP BY  __group__, __group_preset__" % sql, args)
                            
                        exec_groups = [(group, preset, quantity, full_quantity) for group, preset, quantity, full_quantity in cursor]
                        data['exec_groups']= req.args['exec_groups'] = exec_groups
                        paginator = data['paginator']
                        range_start, range_end = paginator.span

                        num_rows = 0
                        num_none_filtered = 0
                        for x, y, quantity, full_quantity in exec_groups:
                            num_rows  = num_rows + quantity
                            num_none_filtered = num_none_filtered + full_quantity
                            delta = full_quantity - quantity
                            if range_start and delta and range_start>num_none_filtered:
                                range_start = range_start - delta
                                range_end = range_end - delta
                                
                        paginator.num_items = num_rows

                        num_filtered_on_page = 0
                        for i, (value_for_group, row_group) in enumerate(row_groups):
                            filtered_row_group = [row for row in row_group if (('id' not in row) or row['id'])]
                            row_groups[i]=(value_for_group, filtered_row_group)
                            range_end = range_end - (len(row_group)  - len(filtered_row_group))
                        if range_end >paginator.num_items:
                            range_end = paginator.num_items
                        paginator.span = range_start, range_end
        return (template, data, content_type)
        
    def resolve_report_number(self, req):
        id = -1
        if req.path_info.startswith('/report'):
            id = int(req.args.get('id','-1'))
        if id == -1:
            last_used_report = req.session.get('last_used_report')
            if last_used_report:
                id = last_used_report
        if id == -1:
            main_reports = self.main_reports
            if main_reports:
                id = main_reports[0]
        if id == -1:
            id = 1
        return id
    
    def available_reports(self, req):
        report_realm = Resource('report')
        cursor = self.env.get_db_cnx().cursor()
        cursor.execute("SELECT id AS report, title "
                         "FROM report ORDER BY report")
        return [(id, title) for id, title in cursor if 'REPORT_VIEW' in req.perm(report_realm(id=id))]
        
    def fields_config(self):
        if self._config is None:
            self._config_lock.acquire()
            try:
                if self._config is None: # double-check (race after 1st check)
                    self._config = self._get_fields_config()
            finally:
                self._config_lock.release()
        return self._config

    def _get_fields_config(self):
        fields = TicketSystem(self.env).get_ticket_fields()
        default = {
            'type' : 'text'
        }
        config ={}
        mappings_config = self.env.config['itteco-report']
        for field in fields:
            cfg = config.setdefault(field['name'], default.copy())
            type = field['type']
            if type=='radio':
                type = 'select'
            cfg['type'] = type
            cfg['field_name'] = field['name']
            if type=='select':
                cfg['options'] = field['options']
            classname = mappings_config.get(field['name']+'.classname')
            if classname:
                cfg['classname'] = classname
        
        for option in mappings_config:
            if option and option.endswith('.synonyms') \
                and config.get(option[:-9]):
                
                for synonym in mappings_config.getlist(option,''):
                    if synonym:
                        config[synonym] = config[option[:-9]].copy()
        self.env.log.debug('itteco-report-config=%s' % config)
        return config
    
    def fields_dict(self, field_groups):
        res = '{'
        config = self.fields_config()
        first = True
        for field_group in field_groups:
            for field in field_group:
                if field['hidden']:
                    continue
                fname = field['title'].lower()
                cfg = config.get(fname)                
                if cfg is None:
                    continue
                    
                if not first:
                    res +=','
                first = False
                res += fname +':' + str(cfg).replace("u'", "'")
        res += '}'
        return res
        
    def get_report_data(self, req, id):
        db = self.env.get_db_cnx()
        _template, data, _content_type = ReportModule(self.env)._render_view(req, db, id)
        return data
    
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