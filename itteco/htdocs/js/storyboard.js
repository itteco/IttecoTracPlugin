    prepareData = function(ticket, target){
        var field_milestone = target.siblings('th').attr('idx');
        var x = defaultPrepare(ticket, target);
        x.data.field_milestone = field_milestone;
        return x;
    }
    
    $(document).ready(function(){
        make_droppable($(".droppable"), acceptTicket, prepareData);        
    });
