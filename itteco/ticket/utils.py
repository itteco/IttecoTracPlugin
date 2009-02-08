from trac.ticket import TicketSystem

def get_fields_by_names(env, names):
    if names:
        names = isinstance(names,basestring) and [names,] or names
        return  [f for f in TicketSystem(env).get_ticket_fields() if f['name'] in names]

def get_tickets_for_milestones(db, milestone, fields, types=None):
    return get_tickets_by_filter(db, fields, milestone=milestone, type=types)
       
def get_tickets_by_ids(db, fields, ids):
    return get_tickets_by_filter(db, fields, id=ids)
    
def get_tickets_by_filter(db, fields, **kwargs):
    cursor = db.cursor()
    name_and_type = fields and [(f['name'], f.get('custom')) for f in fields] or []
    name_and_type += [('id',0),('status',0), ('type',0)]
    
    selected_fields= []
    from_part = " FROM ticket t"
    where_filters = []
    params = []
        
    order_part = None
    custom_fields = []

    def append_filter(field, is_custom):
        vals = kwargs.get(field)
        if vals:
            sql_filter = is_custom and 'tc%s.value' % len(custom_fields) or  "t.%s" % field
            if isinstance(vals,list):
                sql_filter = "%s in (%s) " % ( sql_filter, (len(vals)*"%s,")[:-1])
                params.extend(vals)
            else:
                sql_filter += "=%s"
                params.append(vals)
            where_filters.append(sql_filter)
           
    for field, is_custom in name_and_type:
        if not is_custom:
            selected_fields.append("t.%s" % field)
            if not order_part:
                order_part = "ORDER BY %s" % field
        else:
            custom_fields.append(field)
            cnt = len(custom_fields)
            selected_fields.append("tc%d.value" % cnt)
            from_part = "%s LEFT OUTER JOIN ticket_custom tc%d ON (t.id=tc%d.ticket AND tc%d.name=%%s)" % (from_part,cnt, cnt, cnt)
            if not order_part:
                order_part = "ORDER BY tc%d.value" % cnt
        append_filter(field, is_custom)
    cursor.execute("SELECT %s %s WHERE %s %s" % (",".join(selected_fields), from_part, ' AND '.join(where_filters), order_part), custom_fields+params)
    tickets = []
    
    for row in cursor:
        tickets.append(dict([(field, value)for (field, is_custom), value in map(None, name_and_type, row[:])]))
    return tickets