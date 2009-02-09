var draggable_options ={helper: 'clone', handle: '.drag_handle', opacity: 0.8, 'start' : function(e, ui){ui.helper.css('width',this.offsetWidth+'px');}};
var wbContext = {filter: {field: new Object(), attr: new Object()}};
update_cell = function(cell, ignore_id){
    var row_stat = cell.siblings('.group_holder');
    var group_filter ="[status='"+ cell.attr('status')+"']";
    
    var selector = '.widget';
    if(ignore_id){
        selector +=':not([idx="'+ignore_id+'"])';
    }
    $(".widget", row_stat).each(function(i){
        calcAggregates(this, $(selector, row_stat.siblings()))});
        
    $(".whiteboard_table .group"+group_filter).each(function(i){
        calcAggregates(this, $(selector, $(".whiteboard_table .droppable"+group_filter)))});
    enableAccordionIfAny(cell);
}
calcAllAggregates=function(){
    $(".group", $(".whiteboard_table")).each(function(i){calcAggregates(this, $(".droppable[status='"+$(this).attr('status')+"']", $(".whiteboard_table")))});
    $(".group_holder .widget").each(function(i){calcAggregates(this, $(this).parents(".group_holder").siblings())});
}    
calcAggregates=function(widget, scope){
    var o = $(widget);
    $(".summary .parameter_value[field_name]",o).each(function(i){  
        var obj = $(this);
        var val = getAggregatesValues(obj.attr('field_name'), scope);
        obj.attr(val);
        this.full_stats = val.full_stats;
        if(o.hasClass('calculated')){obj.text(val.sum)};
    });
    setupProgressbar(widget);
}

getAggregatesValues=function(field_name, scope){
    var sum =0, stats ={};
    for(g in window.stats_config){stats[g] = 0;}
    $(".summary .parameter_value[field_name='"+field_name+"']", scope.filter(".widget:visible, *:has(.widget:visible)")).each(
        function(i){
            var t = $(this).parents('.widget');
            var iVal=parseInt($(this).text()); 
            iVal = isNaN(iVal) ? 0 : iVal;
            sum += iVal;
            if(window.stats_status_to_group){
            var g_name = window.stats_status_to_group[t.attr('status')];
            stats[g_name] +=iVal;
            }
        });
    return {'sum': sum, 'full_stats':stats};
}
getProgressbarContext=function(widget){
    var vh = $(".parameter_value[field_name='"+window.progress_field_name+"']", widget);
    return { 'handler' : $('.progress', widget).parent(), 
             'overall_completion': 0, 
             'sum': parseInt(vh.attr('sum')),
             'estimate' : parseInt(vh.text()),
             'full_stats' : vh.attr('full_stats')}
}
colorizeWidget=function(widget){
    var val = parseInt($(".summary .parameter_value[field_name='"+widget.attr('weight_field_name')+"']", widget).text());
    var max_val = parseInt(widget.attr('max_weight'));
    var min_color = widget.attr('min_color');
    var max_color = widget.attr('max_color');
    if(max_val && min_color && max_color){
        var c = "rgb(";
        for(var i=0; i<3; i++){
            if (i!=0) c+=',';
            var l = parseInt("0x"+min_color.substring(1+i*2,1+(i+1)*2),16);
            var h = parseInt("0x"+max_color.substring(1+i*2,1+(i+1)*2),16);
            c+=Math.round(l+(h-l)*(val/max_val));
        }
        c+=")";
        widget.css('background-color',c);
    }
}    
setupProgressbar=function(widget){
    var ctx = getProgressbarContext(widget);
    if(ctx.sum){
        if(ctx.estimate<ctx.sum){
            ctx.handler.addClass("invalidEstimate");
        }else{
            ctx.handler.removeClass('invalidEstimate');
        }
        if(ctx.full_stats && ctx.sum){
            var r = $('.progress tr', ctx.handler).empty();
            var leg = $('dl', ctx.handler).empty();
            var compl_summ = 0;
            for (g in window.stats_config){
                var cfg= window.stats_config[g];
                if(cfg && cfg!=1){
                    var cnt = parseInt(ctx.full_stats[g]);
                    var compl = cnt/ctx.estimate*100;
                    if(!isNaN(compl) && compl >0){
                        ctx.overall_completion += cfg['overall_completion'] ? compl : 0;
                        if(compl_summ<100){
                            r.append($('<td/>').css('width',(compl==Infinity ? 100 : compl)+'%').addClass(window.stats_config[g]['css_class']));
                        }
                        compl_summ +=compl;
                    }
                    leg.append($("<dt/>").text(cfg['label']+":")).append($("<dd/>").text(cnt));
                }
            }
            if(compl_summ<100){
                r.append($('<td/>').css('width',(100-compl_summ)+'%'));
            }
            ctx.handler.show();
            $('.percent', ctx.handler).text(ctx.overall_completion.toFixed(0)+'%');
        }
    }else{
        ctx.handler.hide();
    }
}

change_ticket_view=function(ticket, view){
    $("div.block", ticket).addClass('hidden');
    $('div.'+view, ticket).removeClass('hidden');
    $('.active_tab',ticket).removeClass('active_tab');
    $('.views > .'+view,ticket).addClass('active_tab');
    $('.body', ticket).removeClass('hidden');
    return false;
}
save_ticket = function(form){
    save_ticket_changes($(form).parents('.widget'),$(form).serialize(), defaultPostprocess);
}
defaultPrepare =function(ticket, target) {
    var idx = ticket.attr('idx');
    var data = {'ticket':idx};
   
    var action = getActionToPerform(target.attr('status'), ticket.attr('status'));
    if (action){
        data['tkt_action']=action;
    }
    var parent = ticket.parent();
    update_cell(ticket.parent(), idx);
    var copy = ticket.remove().draggable(draggable_options);
    target.append(copy);
    return {'ticket': copy, 'data':data};
}

teamMemberPrepare=function(ticket, member) {
    var idx = ticket.attr('idx');
    var data = {'ticket':idx, 'tkt_action':'reassign',
         'owner': member.attr('owner'),
         'action_reassign_reassign_owner':member.attr('owner')};
    var newTarget = ticket.parent().siblings('td[action]').andSelf().filter('[action="reassign"]')
    update_cell(ticket.parent(), idx);
    var copy = ticket.remove().draggable(draggable_options);
    newTarget.append(copy);
    return {'ticket': copy, 'data':data};
}

defaultPostprocess = function(ticket, data){
    if (data.result=='done'){
        var mil = data.milestone;
        if(typeof(mil)=='undefined' || current_milestone[mil] || !ticket.hasClass('draggable')){
            for(var key in data){
                $('[field_name="'+key+'"]', ticket).text(data[key]);
                $('[name="field_'+key+'"]', ticket).val(data[key]);
            }
            if(data.status){
                ticket.attr('status', data.status);
                $(".parameter[status]", ticket).addClass('hidden');
                $(".parameter[status='"+data.status+"']", ticket).removeClass('hidden');
            }
            update_cell(ticket.parent());
            colorizeWidget(ticket);
            change_ticket_view(ticket, 'summary');
        }else{
            ticket.remove();
        }
    }
}
save_ticket_changes = function(ticket, send_data, postprocess){
    postprocess = (typeof(postprocess)=='function') ? postprocess : defaultPostprocess;
    $.getJSON(actionUrl, send_data, function(data){ postprocess(ticket, data);});
}
getActionToPerform = function(group_name, ticket_status){
    if (typeof(groups_config) == 'undefined') return;
    var group_cfg = groups_config[group_name];
    if (group_cfg && !group_cfg['statuses'][ticket_status]){
        return group_cfg['action'];
    }
}    

acceptTicket = function(draggable){
    if ($("[idx='"+draggable.attr('idx')+"']", this).length>0 || !draggable.hasClass('widget')){
        return false;
    }
    var source_status = draggable.attr('status');
    var group_name = this.attr('status');
    if (typeof(groups_config) == 'undefined') return false;
    var group_cfg = groups_config[group_name];
    if (typeof(group_cfg) == 'undefined') return false;
    return  group_cfg['src_statuses'][source_status];
}

acceptByTeamMember = function(draggable){
    var cfg = window.groups_config;
    if (typeof(cfg) == 'undefined') return false;
    var o = $(this);
    var dest_group_name= o.attr('status');
    var status= draggable.attr('status');
    var group_cfg = cfg[dest_group_name];
    if (typeof(group_cfg) == 'undefined') return false;
    return  group_cfg['src_statuses'][status];
}
filterTicketsByField = function(e){
    var o = $(this);
    var field = o.parent().parent().attr('filter_field');
    wbContext.filter.field[field]=o.parent().attr(field);
    $(".active_filter", o.parents(".wb-panel-section").add(e.data.selector)).text(o.text());
    filterTickets();
}

filterTicketsByAttr = function(){
    var o = $(this);
    var attr_name = o.parent().parent().attr('filter_attr');
    wbContext.filter.attr[attr_name]=o.parent().attr(attr_name);
    $(".active_filter", o.parents(".wb-panel-section")).text(o.text());
    filterTickets();
}
filterTickets = function(){
    var sel ="";
    var attrs = wbContext.filter['attr'];
    for (var a in attrs){
      if (attrs[a]) sel +='['+a+'="'+attrs[a]+'"]';
    }	
    var fields = wbContext.filter['field'];
    for (var f in fields){
      if (fields[f]) sel +=':has([field_name="'+f+'"]:contains("'+fields[f]+'"))';       
    }
    if(sel!=""){
      $(".draggable").filter(sel).show();
      $(".draggable").not(sel).hide();
    }else{
      $(".draggable").show();
    }
    calcAllAggregates();
}
enableAllAccordions = function(){
    $(".accordion_support").each(function(i){enableAccordionIfAny(this);});  
}
enableAccordionIfAny = function(obj){
    if($(obj).hasClass('accordion_support')){
        $(".widget", obj).each(function(i){putIntoAccordion(this);});  
        $(".widget:last", obj).each(function(i){activateAccordionElement(this);});
    }
}

putIntoAccordion = function(ticket){
    $(".drag_handle", ticket).bind('click', function(e){activateAccordionElement(e.target)});
}
removeFromAccordion = function(ticket){
    $(".drag_handle", ticket).unbind('click');
    $('.body', t).removeClass('hidden');
}
activateAccordionElement = function(handle){
    var h = $(handle)
    var t = h.hasClass('widget') ? h : h.parent();
    $('.body', t.siblings()).addClass('hidden');
    $('.body', t).removeClass('hidden');
    change_ticket_view(t,'summary');
}

createDropFunction = function(prepare, postprocess){
    return function(ev, ui){
        var x = prepare($(ui.draggable), $(this));
        save_ticket_changes(x.ticket,x.data, postprocess);
    };
}

make_droppable = function(obj, acceptCheck, prepare, postprocess){
    obj.droppable({ accept: acceptCheck, activeClass: 'droppable-active', hoverClass: 'droppable-hover', drop: createDropFunction(prepare, postprocess)});
}

$(document).ready(function(){
    enableAllAccordions();
    $('a',$('#wb-section2')).bind('click', {selector:'#wb-section-info-members'}, filterTicketsByField);
    $('a',$('#wb-section4')).bind('click', filterTicketsByAttr);
    $("a", $("#wb-section3")).attr("href", function(i){return $(this).attr("href")+document.location.search;});
    calcAllAggregates();
    $(".item-droppable", $("#wb-section2")).droppable({ accept: acceptByTeamMember, hoverClass: 'item-droppable-active', drop: createDropFunction(teamMemberPrepare)});
    $(".draggable").draggable(draggable_options);
    $(".widget").each(function(i){colorizeWidget($(this))});
    $('#wb-error-panel').ajaxError(function(event, request, settings){
        $(this).append("<li>Error performing action: " + settings.url + "</li>");
    });
});
