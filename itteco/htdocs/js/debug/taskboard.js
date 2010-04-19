milPrepare = function(ticket, target) {
    var x = defaultPrepare(ticket, target);
    x.data.field_milestone = target.children('span:first').text();
    return x;
}
prepareData =function(ticket, target) {
    var new_story = target.siblings('th').attr('idx');
    var old_story = ticket.parent().siblings('th').attr('idx');
    var x = defaultPrepare(ticket, target);
    x.data.new_story = new_story;
    x.data.old_story = old_story;
    return x;
}

$(document).ready(function(){
    make_droppable($(".droppable"), acceptTicket, prepareData);
    
    $(".item-droppable", $("#wb-section3")).droppable({ accept: ".draggable", hoverClass: 'item-droppable-active', drop: createDropFunction(milPrepare)});

    make_droppable($("#black_hole"), ".draggable", 
        function(ticket, target) { 
            return {'ticket' : ticket, 
                    'data': {'ticket': ticket.attr('idx'), 
                        'new_story':'','old_story':ticket.parents('tr').attr('idx'),'field_milestone':''}}});
});
