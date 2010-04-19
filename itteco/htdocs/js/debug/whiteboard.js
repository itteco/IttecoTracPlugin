var contextMenu ;
var draggable_options ={helper: 'clone', handle: '.drag_handle', opacity: 0.8, 'start' : function(e, ui){ui.helper.css('width',this.offsetWidth+'px');}};
var rpc;
window.popup_context = {};

jQuery.fn.outerHTML = function() {
	return $('<div>').append(this.eq(0).clone()).html();
};	

function log(){
    if(typeof console !='undefined' && console.log){
        console.log.apply("", arguments);
    }
}

function WBContext(){
    this.filter = {field: new Object(), attr: new Object()};
    this.cpVisible = false;
    this._save = function(){
        var strVal = "";
        var attrs = wbContext.filter.attr;
        for (var a in attrs){
          if (attrs[a]) strVal +='&filter$attr$'+a+'='+attrs[a];
        }	
        var fields = wbContext.filter.field;
        for (var f in fields){
          if (fields[f]) strVal +='&filter$field$'+f+'='+fields[f];
        }
        strVal+='&cpVisible='+this.cpVisible;
        if(strVal.length>0){
            strVal = strVal.substring(1,strVal.length);            
        }

        $.cookies.set('whiteboardDatabag', strVal);
    }
    this.load = function(){
        var strVal = $.cookies.get('whiteboardDatabag');
        if(strVal){
            var pointer = this;
            $.each(strVal.split('&'), function(){
                var kw = this.split('=');
                var path = kw[0].split('$');
                if(kw.length>1){
                    var len = path.length-1;
                    var obj = pointer;
                    var i =0;
                    while(i<len && obj){
                        if(!obj[path[i]]){
                            obj[path[i]]={};
                        }
                        obj = obj[path[i]];
                        i++;
                    }
                    if(obj){
                        obj[path[len]] = kw[1];
                    }
                }
            })
        }
    }
    this.setFilter = function(type, name, value){
        if (type=='field'){
            this.filter.field[name]=value;
        }else{
            this.filter.attr[name]=value;
        }
        this._save();
    }
    this.toggleControlPanel = function(){
        if(this.cpVisible==true || this.cpVisible=='true'){
            this.cpVisible = false;
        }else{
            this.cpVisible = true;
        }
        this._save();
        return false;
    }
}
var wbContext = new WBContext();

update_cell = function(cell, ignore_id){
    var row_stat = cell.siblings().andSelf().filter('.group_holder');
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
    calcPercentage();
}
calcAllAggregates=function(){
    $(".group", $(".whiteboard_table")).each(function(i){calcAggregates(this, $(".droppable[status='"+$(this).attr('status')+"']", $(".whiteboard_table")))});
    $(".group_holder .widget").each(function(i){calcAggregates(this, $(this).parents(".group_holder").siblings())});
    calcPercentage();
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
calcPercentage=function(){
    var sum = 0;
    $('.whiteboard_table tbody th .parameter_value[field_name="'+window.progress_field_name+ '"]').each(function(i){
        sum += parseInt($(this).text(), 10);
    });
    $('.whiteboard_table thead th .parameter_value').each(function(i){
        var o = $(this);
        var pObj = $('.percentage', o);
        var percentage  = (100*parseInt(o.text())/sum).toFixed(1);
        if(percentage>0){
            if(pObj.length==0){
                pObj = $('<span class="percentage"/>').appendTo(o);
            }
            pObj.text('('+percentage+'%)');
        }else{
            pObj.remove();
        }
    });
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
colorizeWidget=function(widget){
    var tkt_type_cfg = ticket_rendering_config[widget.attr('ticket_type')]
    if(tkt_type_cfg){
        var val = parseInt($(".summary .parameter_value[field_name='"+tkt_type_cfg['weight_field_name']+"']", widget).text());
        val = isNaN(val) ? 0 : val;
        var max_val = parseInt(tkt_type_cfg['max_weight']);
        var min_color = tkt_type_cfg['min_color'];
        var max_color = tkt_type_cfg['max_color'];
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
        var icon = $(".status-icon", widget);
        var iconColor = tkt_type_cfg['icon_bg_color']||'#0F0';
        if(stats_status_to_group){
            var g_name = stats_status_to_group[widget.attr('status')];
            if(g_name && stats_config[g_name] && stats_config[g_name]['overall_completion']){
                iconColor = '#CCC';//grayout completed story
            }
        }
        icon.css('background-color',iconColor);
        icon.text(tkt_type_cfg['icon_text']);
    }
}    
getProgressbarContext=function(widget){
    var vh = $(".parameter_value[field_name='"+window.progress_field_name+"']", widget);
    return { 'handler' : $('.progress', widget).parent(), 
             'overall_completion': 0, 
             'sum': parseInt(vh.attr('sum')),
             'estimate' : parseInt(vh.text()),
             'full_stats' : vh.attr('full_stats')}
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
//Row collapse/expand function
collapseAllRows=function(){
    $("th .widget",$('#whiteboard_table')).each(function(){collapseRow($(this))});
}
collapseRow=function(head_widget){
    $(".body", head_widget).hide();
    $(".widget", head_widget.parent().siblings()).each(function(i){
        var o=$(this); 
        o.addClass("tiny_widget");
        o.bind("mouseover",function(e){
            $("#dyn_hint").text($(".title span", o).text()).show().css({"display":"block","left":e.pageX+"px", "top":e.pageY+25+"px"}).appendTo(document);
            $(this).one("mouseout", function(e){$("#dyn_hint").hide();});
        });
        $(".body, .title > span:not(.ticket-pointer)", o).hide();
        $(".drag_handle", o).unbind('click');
    });
}
expandAllRows=function(){
    $("th .widget",$('#whiteboard_table')).each(function(){expandRow($(this))});
}
expandRow=function(head_widget){
    $(".body", head_widget).show();
    head_widget.parent().siblings().each(function(i){
        var c = $(this);
        $(".draggable", c).each(function(i){
            var o=$(this); 
            o.removeClass("tiny_widget");
            o.unbind("mouseover");
            $(".body, .title > span", o).show();
        });
        enableAccordionIfAny(c);
    });
}
toggleRowCollapse=function(head_widget){
    var expanded = $(".body:visible", head_widget).length>0;
    if (expanded){
        collapseRow(head_widget);
    }else{
        expandRow(head_widget);
    }
}
toggleControlPanel=function(){
    $('#wb-sections, #wb-section-info').add($("#wb-panel-button").children()).toggle();
    return wbContext.toggleControlPanel();;
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
    var copy = ticket.remove().draggable(draggable_options);
    update_cell(parent, idx);
    target.append(copy);
    return {'ticket': copy, 'data':data};
}

teamMemberPrepare=function(ticket, member) {
    var idx = ticket.attr('idx');
    var data = {'ticket':idx, 'tkt_action':'reassign',
         'owner': member.attr('owner'),
         'action_reassign_reassign_owner':member.attr('owner')};
    var group;
    for (var gCfg in window.groups_config){
        if(window.groups_config[gCfg]['statuses']['assigned']){
            group =gCfg;
            break;
        }
    }
    var newTarget = ticket.parent().siblings('td').add(ticket.parent()).filter('[status="'+group+'"]')
    update_cell(ticket.parent(), idx);
    var copy = ticket.remove().draggable(draggable_options);
    newTarget.append(copy);
    return {'ticket': copy, 'data':data};
}

defaultPostprocess = function(ticket, data){
    log('defaultPostprocess', ticket, data);
    if (data.result=='done'){
        var mil = data.milestone;
        var parent = ticket.parent();
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
            colorizeWidget(ticket);
            removeFromAccordion(ticket);
            change_ticket_view(ticket, 'summary');
        }else{
            ticket.remove();
        }
        update_cell(parent);
    }
}
save_ticket_changes = function(ticket, send_data, postprocess){
    postprocess = (typeof(postprocess)=='function') ? postprocess : defaultPostprocess;
    if(typeof(send_data)=='object'){
        send_data['action'] = 'change_task';
    }else{
        send_data='action=change_task&'+send_data;
    }
    $.getJSON(window.urls.action, send_data, function(data){ postprocess(ticket, data);});
}
getActionToPerform = function(group_name, ticket_status){
    if (typeof(groups_config) == 'undefined') return;
    var group_cfg = groups_config[group_name];
    if (group_cfg && !group_cfg['statuses'][ticket_status]){
        var trans = group_cfg['transitions'];
        if(trans){
            return trans[ticket_status];
        }        
    }
}    

acceptTicket = function(draggable){
    return true;
    if ($("[idx='"+draggable.attr('idx')+"']", this).length>0 || !draggable.hasClass('widget')){
        return false;
    }
    var source_status = draggable.attr('status');
    var group_name = this.attr('status');
    if(group_name==draggable.parent().attr('status')) return true;
    if (typeof(groups_config) == 'undefined') return false;
    var group_cfg = groups_config[group_name];
    if (typeof(group_cfg) == 'undefined') return false;
    return  group_cfg['transitions'][source_status];
}

acceptByTeamMember = function(draggable){
    var cfg = window.groups_config;
    if (typeof(cfg) == 'undefined') return false;
    var o = $(this);
    var dest_group_name= o.attr('status');
    var status= draggable.attr('status');
    var group_cfg = cfg[dest_group_name];
    if (typeof(group_cfg) == 'undefined') return false;
    return  group_cfg['transitions'][status];
}
    
toggleTicketsFilter = function(e){
    var o = $(this);
    var by = e.data.filterBy;
    var field = o.parent().parent().attr('filter');
    wbContext.setFilter(by, field, o.parent().attr(field));
    filterTickets();
}

filterTickets = function(){
    var sel ="";    
    var attrs = wbContext.filter['attr'];
    for (var a in attrs){
      if (attrs[a]) {
        sel +='['+a+'="'+attrs[a]+'"]';
      }
      $('.active_filter[filter="'+a+'"]').text($('ul[filter="'+a+'"] > li['+a+'="'+attrs[a]+'"]').eq(0).text());
    }	
    var fields = wbContext.filter['field'];
    for (var f in fields){
      if (fields[f]){
        sel +=':has([field_name="'+f+'"]:contains("'+fields[f]+'"))';
      }
      $('.active_filter[filter="'+f+'"]').text($('ul[filter="'+f+'"] > li['+f+'="'+fields[f]+'"]').eq(0).text());
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
    $('.drag_handle', ticket).unbind('click');
    $('.body', ticket).show();
}
activateAccordionElement = function(handle){
    var h = $(handle)
    var t = h.hasClass('widget') ? h : h.parent();
    $('.body', t.siblings()).hide();
    t.removeClass('tiny_widget');
    $('.body', t).show();
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

bindEventHandlers = function (){
    $('a',$('#wb-section2')).bind('click', {filterBy:'field', selector:'#wb-section-info-members'}, toggleTicketsFilter);
    $('a',$('#wb-section4')).bind('click', {filterBy:'attr'}, toggleTicketsFilter);    
    //expand collapse rows
    $('th .widget .title',$('#whiteboard_table')).bind('click', function(){toggleRowCollapse($(this).parent())});
    $('th.first-item',$('#whiteboard_table')).bind('click', function(){var o=$(this);o.toggleClass('active');if(o.hasClass('active')){expandAllRows()}else{collapseAllRows()};});
    $('#wb-panel-button').bind('click', toggleControlPanel);
}
enableDragAndDrop = function(){
    $('.item-droppable', $('#wb-section2')).droppable({ accept: acceptByTeamMember, hoverClass: 'item-droppable-active', drop: createDropFunction(teamMemberPrepare)});
    $('.draggable').draggable(draggable_options);
}
colorizeWidgets = function(){
    $('.widget').each(function(i){colorizeWidget($(this))});
}
setupAjax = function(){
    $('#wb-error-panel').ajaxError(function(event, request, settings){
        $(this).append("<li>Error performing action: " + settings.url + "</li>");
    });
    
    rpc = $.rpc(
       window.urls.rpc,
       "xml",
       function(server) {
            if(!server || !server.system) {
                alert("Could not get the rpc object ..");
                return;
            }
        }
    );
}
loadContext = function(){
    wbContext.load();
    filterTickets();
    if(wbContext.cpVisible=='true'){
        wbContext.cpVisible =false;
        toggleControlPanel();
    }
}
modifyMilestonesTree = function(){
    var form = $('#mils_options');
    form.bind('submit', function(){$(':checkbox:checked', form).prev().remove();});
    $(':checkbox', form).bind('change', function(){form.trigger('submit');});
}
setupTicketCreation = function(){
    var template = $('#new_ticket_template');
    function setupTicketPrototype(){
        var tkt_prototype = template.clone().attr('id','new_ticket_prototype').appendTo($('#hidden_container'));
        $(".summary .parameter:has([field_name='summary'],[field_name='description'], [field_name='type'])", tkt_prototype).remove();
        $(".edit .parameter:has([name='field_summary'],[name='field_description'], [name='field_type'])", tkt_prototype).remove();
    }

    function postprocessTicketCreation(ticket, data){
        defaultPostprocess(ticket, data);
        if(data.result=='done'){
            var head = $('.title a', ticket);
            var href = head.attr('href');
            var tkt_id =data['id'];
            ticket.attr({'idx':tkt_id, 'id': 'ticket_'+tkt_id});
            var path = href;
            var query = "";
            if(href.indexOf('?')>0){
                path = href.substring(0, href.indexOf('?'));
                query = href.substring(href.indexOf('?')+1);
            }
            href = path.substring(0,path.length-3)+tkt_id + (query!="" ? '?'+query : "") ;
            head.attr('href',href).text('#'+tkt_id);
            head.parent().next().text(data['summary']);
            $(':hidden[name="ticket"]', ticket).val(tkt_id);
            ticket.draggable(draggable_options);
            contextMenu.attachTo($('.ticket-pointer', ticket));
        }
    }

    function setupButtonsForTicketCreation(){
        function cancel(){
            $.fn.colorbox.close();
            return false;
        }

        var link =$('<a class="append_button" href="'+window.urls.popup+'tickets" title="Create Ticket">Add Ticket</a>').click(function(){
            var o = $(this);
            window.popup_context = {
                cancel : cancel,
                setup  :function (root){
                    var found_milestone;
                    for (mil in window.current_milestone){found_milestone = mil;break;}
                    $("[name='field_milestone']", root).val(found_milestone);
                },
                done : function(tkt){
                    log('popup reports that action was done', tkt);
                    tkt.result = 'done';//hack to be removed
                        
                    var targetVal = popup_context['new_story'];
                    if(isNaN(parseInt(targetVal))){
                        targetVal='';
                    }
                    var widget=$('#new_ticket_prototype .widget').clone(). 
                        attr('ticket_type',tkt.type). 
                        appendTo($('#whiteboard_table tbody tr[idx="'+ targetVal+'"] > td[status]:first'));
                    $('.progress', widget).parent().remove();
                    $('[field_name="description"]', widget).text(tkt.description);
                    
                    log('before enabling drag and drop', widget);
                    widget.addClass('draggable').draggable(draggable_options);
                    rpc.ticketconfig.trace(
                        function(resp){
                            postprocessTicketCreation(widget, tkt);
                        },
                        tkt.id,
                        targetVal
                    )
                    return cancel();
                }
            }
            popup_context['new_story']=o.parents(".group_holder").attr('idx');
            $.fn.colorbox(
                {
                    href: window.urls.popup+'tickets',
                    open: true,
                    title: 'Create Ticket'
                }
            )
            return false;
        });
        $($("<li/>").append(link)).appendTo($('#whiteboard_table tbody th .views'));
    }
    if(template.length>0){
        setupTicketPrototype();
        setupButtonsForTicketCreation();
    }
}

function showPopup(ticket, popupName){
    function cancel(){
        $.fn.colorbox.close();
        return false;
    }

    var widget = $('#ticket_'+ticket);
    if(widget.length>0){
        window.popup_context = {
            cancel : cancel,
            setup  :function (root){},
            done : function(tkt){
                log('popup reports that action was done', tkt);
                tkt.result = 'done';//hack to be removed
                defaultPostprocess(widget, tkt);                    
                return cancel();
            }
        }
        $.fn.colorbox(
            {
                href: window.urls.popup+popupName+'/'+ticket,
                open: true,
                title: 'Edit Ticket'
            }
        )

    }
}

function showQuickEditor(ticket){
    showPopup(ticket,'tickets');
}
function showCommentEditor(ticket){
    showPopup(ticket,'comment');
}
function showFullEditor(ticket){
    document.location = window.urls.base+'/ticket/'+ticket;
}

function ContextMenu() {
    jQuery('body').append('<div id="inline-menu"><div id="inline-menu-body"></div></div>');
    
	var inlineMenu 		= jQuery('#inline-menu');
	var inlineMenuBody 	= jQuery('#inline-menu-body');
	// show menu
	function showInlineMenu(element) {
        log('element', element, jQuery(element));
		offset = jQuery(element).offset();
		inlineMenu.css('left',offset.left);
		inlineMenu.css('top',offset.top);
		menuItems = getInlineMenu(element);
		if (menuItems) {
			inlineMenuBody.html('<div>' + jQuery(element).outerHTML() + '</div>' + menuItems);
			inlineMenu.show();	
		}
	}
	
	// get menu items
	function getInlineMenu(element) {
		var ticket = jQuery(element).text().substr(1);
		if (jQuery(element).hasClass('ticket-pointer')) {
			menu = '<ul>';
			menu += '<li class="inline-menu-item-ticket-quick-editor"><a href="#quickeditor" onclick="showQuickEditor(\'' + ticket + '\')">Quick Editor</a></li>';
            menu += '<li class="inline-menu-item-ticket-comment"><a href="#comment" onclick="showCommentEditor(\'' + ticket + '\')">Comment</a></li>';
			menu += '<li class="inline-menu-item-ticket-full-editor"><a href="#fulleditor" onclick="showFullEditor(\'' + ticket + '\')">Full Editor</a></li>';
			menu += '</ul>';
		}
		return menu;
	}

    function attach(obj){
        $(obj).mouseover(
            function() {
                showInlineMenu(this);
            }								
        );
    }
    
	// events
    this.attachTo = attach;
    
    attach(jQuery('.ticket-pointer'));
    
	jQuery(inlineMenu).hover(
		function(event) {},
		function(event) {
			jQuery(inlineMenu).hide();
		}
	);
}

$(document).ready(function(){
    setupAjax();
    bindEventHandlers();
    enableAllAccordions();
    enableDragAndDrop();
    colorizeWidgets();
    modifyMilestonesTree();
    setupTicketCreation();
    contextMenu = new ContextMenu()
    loadContext();
});
