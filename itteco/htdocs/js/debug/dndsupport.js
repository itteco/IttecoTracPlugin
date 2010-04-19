dragable_options = {helper:'clone',handle: 'dt',opacity: 0.8, 'start' : function(e, ui){ui.helper.css('width',this.offsetWidth+'px');}};

searchViaJson=function(url, params){
    $.getJSON(url,params,
        function(data){
            $.each(data.items, function(i,item){
                var refId = item.href.substr(item.href.lastIndexOf('/')+1);
                var active = (('x'+document.location.pathname)!=('x'+item.href) && 
                    $('#links_'+item.type+'_container > input[value="'+refId+ '"]').length==0);
                $('#results').append($('<div/>').attr({'item_type':item.type, 'idx':item.idx, 'class': active ? 'draggable' : 'draggable_inactive'}).
                    append($('<dl/>').
                        append($('<dt/>').append($('<a/>').attr({'href': item.href, 'class' :'searchable', 'idx':item.idx, 'target':'_blank'}).append(item.title))).
                        append($('<dd class="description"/>').append(item.excerpt)).
                        append($('<dd class="author"/>').
                            append(item.author ? $('<span class="author"/>').text('By '+item.author) : '').
                            append($('<span class="date"/>').text(item.date)))));
            });
            $(".draggable").draggable(dragable_options); 
        });
}
removeLinkFunction=function(obj){
    var o=$(obj);
    var iType = o.attr('item_type');
    $('#links_'+iType+'_container').children('input[value="'+o.attr('linkid')+'"]').remove();
    $('.draggable_inactive:has(a[href="'+o.siblings("a:first").attr('href')+'"])', $('#results')).removeClass("draggable_inactive").addClass("draggable").draggable(dragable_options).draggable('enable');
    o.parent().remove(); 
    return false;
};
dropFunction =function(ev, ui) {
    var idx = $(ui.draggable).attr('idx');
    var iType = $(ui.draggable).attr('item_type');
    var lid = $('.searchable', $(ui.draggable));
     
    var refId = lid.attr('href').substr(lid.attr('href').lastIndexOf('/')+1);
    $("a[href!='#'][target!='_blank']", $('#traceability')).attr('target','_blank');
    var removeLink = $('<a href="#" class="action_button" onclick="removeLinkFunction(this); return false;">Remove</a>').attr('linkid',refId).attr('item_type',iType); 
    var appended = false;
    var new_item = $("<li/>").append(lid.clone().addClass("new_link")).append("&nbsp;").append(removeLink);
    $("ul > li > a[href!='#']", this).each(function(i){
        var this_idx = $(this).attr('idx');
        if(this_idx>idx || (this_idx==idx && this.innerHTML>lid.text())){
            $(this).parent().before(new_item);
            appended = true;
            return false;
        }
    });
    if(!appended){
        $(this).children("ul").append(new_item);
    }
    $(ui.draggable).removeClass("draggable").addClass("draggable_inactive").draggable("disable");
    $('#links_'+iType+'_container').append($('<input type="hidden"/>').attr({'name':'links_'+iType,'value':refId}));
}
performSearch = function(form, url){
    $('#results').empty();
    searchViaJson(url, $(form).serialize()); 
    return false;
}
$(document).ready(function(){
    $(".draggable").draggable(dragable_options);
    $(".outblock").droppable({ accept: ".draggable", activeClass: 'droppable-active', hoverClass: 'droppable-hover', drop: dropFunction});
})