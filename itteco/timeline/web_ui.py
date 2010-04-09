from trac.core import Component, implements
from trac.resource import Resource
from trac.web import IRequestFilter

class IttecoTimelineFilterModule(Component):

    implements(IRequestFilter)
    
    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler
    
    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/timeline') and data:
            events = data.get('events')
            if events:
                data['events'] = self._filter(events)
        return template, data, content_type
        
    def _filter(self, events):
        for e in events:
            event = e['event']
            if not event or len(event)<3:
                yield e
                continue
            descr = event[3]
            if not descr or len(descr)==0:
                yield e
                
            realm = descr[0]
            if not realm or not isinstance(realm, Resource):
                yield e
                continue
            if realm.realm!='ticket':
                yield e
                continue
                
            ticket_type = descr[6]
            if not ticket_type or ticket_type[0]!='$':
                yield e
                    
            

