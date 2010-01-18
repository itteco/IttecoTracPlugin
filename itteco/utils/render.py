from genshi.builder import tag
from trac.web.chrome import add_script
from itteco import __version__

def hidden_items(field_id, ids):    
    data = []
    for id in ids:
        data.append(tag.input(type="hidden", id=field_id, name=field_id, value=id))
    return tag.span(id=(field_id+'_container'), *data)

def as_js_dict(obj):
    obj = (isinstance(obj, list) or isinstance(obj, set)) and obj or [obj,]
    return "{%s}" % ",".join(["'%s':1" % x for x in obj])
    
def get_powered_by_sign():
    return tag.p("Powered by ", 
            tag.a(tag.strong("IttecoTracPlugin %s" % __version__), href="http://tracplugin.itteco.com/"), 
            tag.br(), tag("By ", tag.a("Itteco Software", href="http://www.itteco.com"),),class_="left")
    
def add_jscript(req, scripts, debug=False):
    if isinstance(scripts, basestring):
        scripts = [scripts,]
    for script in scripts:
        add_script(req, map_script(script, debug))
        
def map_script(script, debug=False):
    prefix = 'itteco/js/'
    sufix = '.min.js'
    if debug:
        prefix = prefix+'debug/'
        sufix = '.js'
    return prefix+script[:-3]+sufix