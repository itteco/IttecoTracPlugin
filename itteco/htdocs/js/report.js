var dragHelper = '<div id="dragHelper"><div>Dragging <span class="quantity">0</span> tickets.</div></div>';
var draggable_options = {helper:function(e){return $(dragHelper).get();}, opacity: 0.8, start: function(e, ui){$('.quantity', ui.helper).text($(":checked").length || 1);}};
decorateDropBox = function(){
    var box = $('#dropbox');
    $('.control-panel a', box).bind('click', function(e){
        var content = $('#dropbox .content');
        if(content.is(":visible")){
            box.attr('savedHeight', box.height());
        }
        var cp = $(this).parent();
        cp.siblings().andSelf().toggle();
        content.toggle();
        if(content.is(":visible")){
            box.resizable("enable");
            if(box.is('[savedHeight]')){
                box.height(box.attr('savedHeight')+'px');
            }
        }else{
            box.resizable("disable");
            box.height(cp.height()+3);
        }
    });
    $('.report-result:odd', box).addClass('odd');
    $('.report-result:even', box).addClass('even');
    box.draggable();
    box.resizable();
}
syncGroupIds = function(){
    var bodyGroups = $('#content .report-result');
    $('#dropbox .content .report-result').each(function(i){
        var dropBoxGroup = $(this);
        var pattern = dropBoxGroup.text().replace(/\n\s*/, '');
        dropBoxGroup.attr('idx', 'group_'+i);
        
        bodyGroups.not('[idx]').each(function(i){
            var contentGroup = $(this);
            if(contentGroup.text().replace(/\n\s*/, '')==pattern){
                contentGroup.attr('idx', dropBoxGroup.attr('idx'));
                return true;
            }
        });
    });
}
disableTickets = function(tkts){
    $(":checked", tkts).attr('disabled', 'disabled');
}
enableTickets = function(tkts){
    $(":checked", tkts).removeAttr('disabled').attr('checked', false);
    $('td.ticket',tkts).draggable(draggable_options);
}
enableDragAndDrop = function(){
  var tkts = $('.listing tbody td.ticket');
  tkts.css('cursor','move').prepend('<input type="checkbox"/>');
  tkts.each(function(i){var t = $(this); t.attr('ticket', $('a', t).text().substring(1)); });
  tkts.draggable(draggable_options);
  $('#dropbox .report-result').droppable({accept:'.ticket', activeClass: 'droppable-active', hoverClass: 'droppable-hover', drop: dropTicketsToGroup});
}
dropTicketsToGroup = function(e, ui){
    var tkts = $('.listing tbody td.ticket:has(:checked)');
    if(tkts.length==0){
        tkts = ui.draggable;
    }
    disableTickets(tkts)
    executeAjaxAction(tkts, $(this));
}
getMatchesText = function(cnt){
    var txt = '(No matches)';
    if (cnt>0){
        if(cnt==1){
            txt = '(1 match)';
        }else{
            txt = '('+cnt+' matches)';
        }
    }
    return txt;
}
calculateGroupMatches= function(){
    var groupBoxGroups= $('#dropbox .content .report-result');
    
    $('#content .report-result').each(function(i){
        var o = $(this);
        var txt = getMatchesText($('td.ticket', o.next()).length);
        $('.numrows', o).text(txt);
        $('.numrows', groupBoxGroups.filter('[idx="'+o.attr('idx') +'"]')).text(txt);
    })
}
executeAjaxAction = function(tickets, target){
    var ids = $.map(tickets,function(tkt, i){return $('a',tkt).text().substring(1)});
    $.getJSON(document.location.pathname, {action: 'execute', tickets: ids.join(','), presets: target.attr('preset')}, 
        function(data){ 
            if (data){
                if(data.tickets){
                    var selectors = [];
                    $.each(data.tickets, function(){
                        selectors.push(' td.ticket[ticket="'+this+'"]');
                    });
                    var rows = $(selectors.join(','), '.listing tbody').parent().remove();
                    
                    var target_table = $('#content .report-result[idx="'+target.attr('idx') +'"]').next();
                    if(target_table && target_table.length>0){
                        $('tbody', target_table).append(rows);
                    }else{
                        var sMatch = $('.numrows', target);
                        var s = sMatch.text().match(/\d+/);
                        var currQuantity = 0;
                        if (s && s.length>0){
                            currQuantity = parseInt(s[0], 10);                            
                        }
                        sMatch.text(getMatchesText(currQuantity+rows.length));
                    }
                    calculateGroupMatches();
                    enableTickets(rows);
                }
            }
        });
}
$(document).ready(function(){
    decorateDropBox();
    syncGroupIds();
    enableDragAndDrop();
});