prepareData = function(ticket, target){
    var old_mil=ticket.parent().siblings('th').attr('idx');
    var new_mil = target.siblings('th').attr('idx');
    var x = defaultPrepare(ticket, target);
    if(old_mil!=new_mil){
        x.data.field_milestone = new_mil;
    }
    return x;
}

$(document).ready(function(){
    make_droppable($(".droppable"), acceptTicket, prepareData);        
});
