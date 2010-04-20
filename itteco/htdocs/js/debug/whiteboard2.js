(function($){    
    $.fn.extend({
        whiteboard: function(wbcontext, options){
            var root = $(this);
            var elem = root.get(0);
            
            function noop(){}
            if(!window.console){
                window.console={log:noop}
            }
            
            if (typeof wbcontext == 'string') {
                var args = Array.prototype.slice.call(arguments, 1);
                var res = $.data(document, 'whiteboard'+root.attr('id'))[wbcontext].apply(this, args);
                if (res != undefined) {
                    return res;
                }
                return this;
            }

            var rpc, isInitialized = false;
            var ctx = {
                managersQuantity :2,
                managers : {},
                reportReady: function(manager){
                    log('manager ' + manager.name + ' reported that it is ready');
                    this.managers[manager.name]=manager;
                    var cnt  =0;
                    for(m in this.managers){
                        cnt = cnt +1;
                    }

                    if(cnt==this.managersQuantity){
                        isInitialized = true;
                        log('all managers ready. notifying.', this.listeners);
                        if (typeof this['listeners'] !='undefined'){
                            for (idx in this.listeners){
                                log('notify listener '+idx);
                                this.listeners[idx]();
                            }
                        }                
                    }
                },
                addListener: function(listener){
                    if (typeof this['listeners'] =='undefined'){
                        this['listeners'] = []
                    }
                    this.listeners.push(listener);
                },
                tzoffset : new Date().getTimezoneOffset(),
                debug : false
            };

            var defaults = {
                delay     : 5000,
                rpcurl    : '/login/xmlrpc',
                baseurl   : '',
                timerurl  : '',
                debug     : false,
                scopeitem : {
                    types : ['story', 'enhancement'],
                    weight: 'business_value',
                    weightlabel : 'BV'
                },
                workitem : {
                    types : '*',
                    weight: 'complexity',
                    weightlabel : 'CP'
                },
                groups    : [
                    {
                        name : 'Planning',
                        status : ['new', 'reopened']
                    },
                    {
                        name : 'In Progress',
                        status : ['assigned', 'accepted']
                    },
                    {
                        name : 'Done',
                        status : ['closed'],
                        overall_completion : true
                    }
                ],
                transitions : [
                    {
                        newstatus : 'assigned',
                        oldstatuses : ['new', 'assigned', 'reopened'],
                        action : 'reassign'
                    },
                    {
                        newstatus : 'reopened',
                        oldstatuses : ['closed'],
                        action : 'reopen'
                    }
                ],
                avatarResolver : function(options, owner){
                    return options.baseurl +'/chrome/itteco/images/avatar.png'
                }
            };

            var settings = $.extend(defaults, {});
            for(var i=1; i < arguments.length; i++){
                settings = $.extend(settings, arguments[i]);
            }

            function log(){
				if(typeof window.console =='undefined'){
					window.console = {log: function(){}};
				}
                if (settings.debug){
                    console.log.apply("", arguments);
                }
            }
            var statusToGroupName = {}, transitionMatrix= {};
            function initMatrix(){
                $.each(settings.groups, function(i, group){
                    $.each(group.status, function(j, status){
                        statusToGroupName[status] = group.name;
                    });
                    transitionMatrix[group.name] = {};
                });
                var captureAllAction;
                $.each(settings.transitions, function(i, transition){
                    if(transition.newstatus=='*'){
                        captureAllAction = transition.action;
                    }
                    $.each(transition.oldstatuses, function(j, status){
                        var groupName = statusToGroupName[transition.newstatus];
                        if(typeof groupName!='undefined'){
                            transitionMatrix[groupName][status] = transition.action;
                        }
                    });
                });
                if(captureAllAction!=undefined){
                    $.each(settings.groups, function(i, group){
                        $.each(group.status, function(j, status){
                            transitionMatrix[group.name][status] = captureAllAction;
                        });
                    });
                }
                
                log('transitionMatrix', transitionMatrix);

            }
            
            initMatrix();

            function TransportManager(){
                this.name = 'transport';
                var pointer = this;
                log('init TransportManager with ', settings.rpcurl);
                $.rpc(
                   settings.rpcurl,
                   "xml",
                   function(server) {
                        if(!server || !server.system) {
                            log("Could not get the rpc object ...");
                            return;
                        }
                        pointer.proxy = server;
                        ctx.reportReady(pointer);
                    }
                );
                
                this.isReady = function(){
                    return (typeof proxy == 'undefined');
                }
                
                function responseHandler(func){
                    return function(resp){
                        log('responseHandler', resp, resp.faultString);
                        if(resp && resp.error){
                            alert(resp.error.faultString);
                        }else{
                            func(resp.result);
                        }
                    }
                }
            }

            function TicketManager(){                
                this.name = 'tickets';
                log('init ticket manager');
                var stories, tickets, fullProgress, renderer, popupManager;
                
                function reset(){
                    stories = {};
                    tickets = {};
                    fullProgress = new ProgressBar();
                    root.empty();
                    renderer = new Renderer();
                    popupManager = new PopupManager();
                }
                
                reset();
                
                function isTicketVisible(ticket){
                    return (wbcontext.owner=='all' || ticket.owner==wbcontext.owner)
                            && (wbcontext.ticket_type=='all' || ticket.type==wbcontext.ticket_type);
                }
                
                function isScopeItem(ticket){
                    var type = ticket.type;
                    if(typeof type=='undefined'){
                        return false;
                    }
                    
                    return settings.scopeitem.types.indexOf(type)!=-1;
                }
                function decorateScopeElement(story, uid){
                    story.$local$uid = uid;
                    story.groupItems = {};
                    story.progress = new ProgressBar(fullProgress);
                    story.remove = function(ticket){
                        var groupName = statusToGroupName[ticket.status];
                        if(typeof groupName!='undefined'){
                            log('removing ', ticket, 'from group '+groupName+' of story', story);                            
                            story.groupItems[groupName] = story.groupItems[groupName].filter(function(elem, idx, array){
                                if(elem.id ==ticket.id){
                                    story.progress.dec(groupName, ticket[settings.workitem.weight]);
                                }
                                return elem.id !=ticket.id;
                            });
                        }else{
                            log('failed to define group for ticket', ticket, 'ignoring');
                        }
                    }
                    story.add = function(ticket, groupName){
                        log('story.add', ticket, 'to group '+groupName);
                        var oldTicket = tickets[ticket.id];
                        if(typeof oldTicket!='undefined'){
                            this.remove(oldTicket);
                        }
                        tickets[ticket.id] = ticket;
                        ticket.story = story;
                        if(typeof groupName =='undefined'){
                            groupName = statusToGroupName[ticket.status];
                        }
                        if(typeof groupName!='undefined'){
                            story.progress.inc(groupName, ticket[settings.workitem.weight]);
                            log('pushing', ticket, 'to group '+groupName+' for story', story);
                            story.groupItems[groupName].push(ticket);
                        }else{
                            log('failed to define group for ticket', ticket, 'ignoring');
                        }
                    }
                    $.each(settings.groups, function(j, group){
                        story.groupItems[group.name]=[];
                    });
                }
                    
                function Renderer(){
                    
                    function renderWhiteboardSummary(){
                        var ui = $('.w-whiteboard-summary', root);
                        if(ui.length==0){
                            ui = $('<div class="w-whiteboard-summary"></div>').prependTo(root);
                        }
                        ui.empty();
                        var info = fullProgress.info();
                        $.each(info.intervals, function(idx, item){
                            ui.append(item.label+': ')
                              .append('<span class="value">'+item.absvalue+' '+settings.workitem.weightlabel+'</span>')
                              .append('<span>|</span>');
                        });
                    }
                    
                    function makeCollapsable(widget, widgetHeader, widgetBody){
                        widgetHeader.unbind().click(function(e) {                        
                            if (widget.hasClass('w-widget-collapsed')) {
                                widgetBody.show();
                            }else {
                                widgetBody.hide();
                            }
                            widget.toggleClass('w-widget-collapsed');
                        });
                        if(widget.hasClass('w-widget-collapsed')){
                            widgetBody.hide();
                        }
                    }
                    function makeDraggable(widget, widgetHeader){
                        widget.draggable('destroy').draggable(
                            {
                                helper: 'clone', 
                                handle : widgetHeader, 
                                start : function(e, ui){
                                    $(ui.helper).width(widget.width());
                                },
                                stop: function(){}
                            }
                        );
                    }
                    
                    function enableToolbarToggling(root){
                        $('.w-ticket', root).hover(
                            function(){
                                var sitem = $(this);
                                sitem.addClass('hover');
                                setTimeout(function() {
                                        if (sitem.hasClass('hover')) {
                                            sitem.find('.s-icon-bar').fadeIn();		
                                        }
                                    }, 500
                                );
                                
                            },
                            function(){
                                var sitem = $(this);
                                sitem.removeClass('hover');
                                $(this).find('.s-icon-bar').fadeOut('fast');
                            }
                        );

                        $(root).hover(
                            function(){
                                var sitem = $(this);
                                sitem.addClass('hover');
                                setTimeout(function() {
                                        if (sitem.hasClass('hover')) {
                                            sitem.find('.w-story-summary .s-icon-bar').fadeIn();		
                                        }
                                    }, 500
                                );
                                
                            },
                            function(){
                                var sitem = $(this);
                                sitem.removeClass('hover');
                                $(this).find('.w-story-summary .s-icon-bar').fadeOut('fast');
                            }
                        );
                    }
                    function makeDroppable(area, story, groupName){
                        area.droppable('destroy').droppable(
                            {
                                accept: function(draggable){
                                    return isWidgetTransferableTo(draggable, groupName);
                                },
                                hoverClass: 'item-droppable-active', 
                                drop: function(e, ui){
                                    log('dropping ticket to group '+groupName);
                                    var ticket = getTicketByWidget(ui.draggable);
                                    setTimeout(function(){
                                        var oldStory = ticket.story;
                                        oldStory.remove(ticket);
                                        story.add(ticket, groupName);
                                        renderScopeElement(oldStory);
                                        var attrs = {action : transitionMatrix[groupName][ticket.status]};
                                        if(wbcontext.board=='stories'){
                                            attrs['milestone'] = story.id;
                                        }
                                        updateTicket(ticket, attrs, true);
                                        if (oldStory!=story){
                                            if(wbcontext.board!='stories'){
                                                ctx.managers.transport.proxy.ticketconfig.trace(
                                                    noop,
                                                    ticket.id,
                                                    story.id||'',
                                                    oldStory.id||''
                                                );
                                            }

                                            renderScopeElement(story);
                                        }

                                    }, 200);
                                }
                            }
                        );
                    }
                    function getTicketByWidget(widget){
                        var id = widget.attr('id');
                        var ticketId = id.substr("ticket-widget-".length);
                        return tickets[ticketId];
                    }
                    function isWidgetTransferableTo(widget, groupName){
                        var ticket = getTicketByWidget(widget);
                        var action = transitionMatrix[groupName][ticket.status];
                        return typeof action!='undefined';
                    }
                    function createTicketToolbar(ticket, realm, extraClass){
                        var isAScopeElement = isScopeItem(ticket) || (extraClass !=undefined && wbcontext.board=='stories');
                        if(typeof extraClass == 'undefined'){
                            extraClass = ''
                        }
                        var toolbar = $('<div class="s-columns w-ticket-toolbar '+extraClass+'">'+
                                    '<div class="s-column-left">'+
                                        (ticket.id ?
                                            '<div class="s-avatar-wrapper s-avatar-wrapper-20">'+
                                                '<img class="s-avatar" width="20" height="20" alt="'+ticket.owner+'" title="'+ticket.owner+'" src="'+settings.avatarResolver(settings, ticket.owner)+'" />'+
                                            '</div>'+
                                            '<div class="w-ticket-values">'+
                                            (ticket[settings.scopeitem.weight]||'0') +' <em>'+settings.scopeitem.weightlabel+'</em>'+
                                            (settings.scopeitem.weight != settings.workitem.weight ? 
                                                ('  <span>|</span> '+
                                                    (ticket[settings.workitem.weight]||'0') +' <em>'+settings.workitem.weightlabel+'</em>'
                                                )
                                                : ''
                                            )+
                                            ' </div>'
                                            : ''
                                        )+
                                    '</div>'+
                               '</div>')
                                .append(
                                    $('<div class="w-column-right">').append(
                                        $('<ul class="s-icon-bar">'+
                                            (ticket.id ? '<li><a href="'+settings.baseurl+'/popup/'+realm+'/'+ticket.id+'" class="s-icon-button s-icon s-icon-edit-quick">View</a></li>' : '') +
                                            (ticket.id ? '<li><a href="'+settings.baseurl+'/'+realm+'/'+ticket.id+'" class="s-icon-button s-icon s-icon-edit">Edit</a></li>' : '')+
                                            (ticket.id ? '<li><a href="'+settings.baseurl+'/popup/comment/'+realm+'/'+ticket.id+'" class="s-icon-button s-icon s-icon-comments">Comments</a></li>' : '') +
                                            (isAScopeElement ? '<li><a href="#" class="s-icon-button s-icon s-icon-ticket-add">Add ticket</a></li>' : '')+
                                            (ticket.id && !isAScopeElement && settings.timerurl!='' ? '<li><a href="'+settings.timerurl+'?title='+encodeURIComponent('#'+ticket.id+' '+ ticket.summary)+'" class="s-icon-button s-icon s-icon-timetrack" title="Time Track">Time Track</a></li>' : '')+
                                        '</ul>')
                                    )
                                );

                        $('.s-icon-ticket-add', toolbar).click(function(){
                            popupManager.createNewTicket(ticket);
                            return false;
                        });
                        
                        $('.s-icon-comments', toolbar).click(function(){
                            popupManager.comment(ticket, this);
                            return false;
                        });

                        $('.s-icon-edit-quick', toolbar).click(function(){
                            popupManager.edit(ticket, this);
                            return false;
                        });
                        
                        $('.s-icon-timetrack', toolbar).click(function(){
                            popupManager.popup(this);
                            return false;
                        });
                        
                        return toolbar;

                    }
                    function createTicketWidget(ticket, extraClasses){
                        var header;
                        if(typeof extraClasses =='undefined'){
                            extraClasses = '';
                        }
                        var widget = $(
                            '<div id="ticket-widget-'+ticket.id+'" class="w-ticket w-ticket-'+ticket.type+' s-widget-nofx '+extraClasses+'">')
                            .append( header = 
                            $('<div class="w-ticket-header">'+
                                '<h6>'+
                                    '<span class="w-ticket-type w-ticket-type-'+ticket.type+'" title="'+ticket.type.substring(0,1).toUpperCase()+ticket.type.substring(1)+'">'+ticket.type.substring(0,1).toUpperCase()+'</span>'+
                                    '<span class="w-ticket-number">'+
                                        '<a href="'+settings.baseurl+'/ticket/'+ticket.id+'">#'+ticket.id+'</a>'+
                                    '</span>&nbsp;'+ticket.summary+
                                '</h6>'+
                            '</div>'));
                        var body =$(
                            '<div class="w-ticket-body">'+
                                '<div class="w-ticket-description">'+ticket.description+'</div>'+
                            '</div>');
                        
                        body.append(createTicketToolbar(ticket, settings.workitem.realm));
                        widget.append(body);
                        makeCollapsable(widget, header, body);
                        makeDraggable(widget, header);
                        return widget;
                    }
                    
                    function renderScopeElement(story){
                        var widgetId = 'story-widget-'+story.$local$uid;
                        var widget= $('#'+widgetId, root);
                        if(widget.length>0){
                            widget.empty();
                        }else{
                            root.append(
                                widget = $('<div id="'+widgetId+ '" class="s-block w-story s-widget-collapsible s-widget-nofx"/>')
                            );
                        }
                        
                        var header, body, sections;
                        widget
                            .append(header = $('<div class="s-block-header s-widget-handler"/>'))
                            .append( body = $('<div class="s-block-body s-widget-body"></div>')
                                .append(sections = $('<div class="w-story-sections"/>'))
                            );
                        header.append(createProgressBar(story.progress))
                            .append('<h4 class="w-widget-collapsible-handler">'+(story.id && story.id != story.summary ? '#'+story.id : '')+'&nbsp;'+story.summary+'</h4>')
                            
                        var descrSection = 
                            $('<div class="w-story-section"/>')
                                .append(
                                    createTicketToolbar(story, settings.scopeitem.realm, 'w-story-summary')
                                )
                                .append($('<div class="w-story-description">'+(story.description || '')+'</div>'));
                        var maxHeight = descrSection.height();

                        sections.append(descrSection);
                        
                        $.each(settings.groups, function (groupIdx, group){
                            var groupSection = $('<div class="w-story-section">'+
                                '<h5 class="w-story-section-header">'+group.name+'</h5>')
                            sections.append(groupSection);
                            var extraClasses = group.accordion =='true' ? 'w-widget-collapsed' : '';

                            $.each(story.groupItems[group.name], function(ticketIdx, ticket){
                                if(isTicketVisible(ticket)){
                                    groupSection.append(createTicketWidget(ticket, extraClasses));
                                }
                            });
                            makeDroppable(groupSection, story, group.name);
                            maxHeight = Math.max(maxHeight, groupSection.height());
                        });
                        
                        var width = 90 / sections.children().length +'%';
                        sections.children().each(function(){
                            $(this).css({'width': width, 'min-height': maxHeight});
                        });
                        makeCollapsable(widget, header, body);
                        enableToolbarToggling(widget);
                        renderWhiteboardSummary();
                    }
                    
                    function createProgressBar(progressbar){
                        var storyProgressUI, barUI
                        var info =  progressbar.info();
                        if(isNaN(info.done)){
                            return '';
                        }
                        storyProgressUI = $('<div class="t-story-progress"/>');
                        storyProgressUI.append(barUI = $('<div class="t-progress-bar"/>'));
                        log('rendering progress bar for info',info);
                        $.each(info.intervals, function(idx, item){
                            barUI.append('<div class="t-progress-bar-item t-progress-bar-item-'+item.name+'" style="width: '+item.percentage+'%;"></div>');
                        });                        
                        storyProgressUI.append('<span>'+info.done+'%</span>');
                        
                        return storyProgressUI;
                    }

                    function renderBurndown(){
                        var params = {
                            path : "",
                            settings_file : encodeURIComponent(settings.baseurl+"/whiteboard/chart_settings/"+wbcontext.milestone)
                        };
                        swfobject.embedSWF(settings.baseurl+"/chrome/itteco/charts/amstock/amstock.swf", root.attr('id'), "100%", "400", "9.0.0","expressInstall.swf", params);
                    }

                    /**/
                    this.renderBurndown = renderBurndown
                    this.makeCollapsable = makeCollapsable;
                    this.createTicketToolbar=createTicketToolbar;
                    this.createTicketWidget=createTicketWidget;
                    this.renderScopeElement = renderScopeElement;
                    this.renderWhiteboardSummary = renderWhiteboardSummary;
                }
                
                function ProgressBar(aggregateProgressbar){
                    var data  = {};
                    var sum = 0;
                    var completion_groups = [];
                    $.each(settings.groups, function(i, group){
                        data[group.name] = 0;
                        if(group.overall_completion){
                            completion_groups.push(group.name);
                        }
                    });
                    function normilize(val){
                        if(typeof val=='undefined'){
                            return 0;
                        }
                        try{
                            return new Number(val);
                        }catch(e){
                            log('failed to transform to number', e ,'returning 0.');
                        }
                        return 0;
                    }
                    function change(groupName, delta){
                        var val = data[groupName];
                        if(typeof val=='undefined'){
                            val = 0;
                        }
                        data[groupName]=val+delta;
                        sum= sum+ delta;
                        if(typeof aggregateProgressbar!='undefined'){
                            aggregateProgressbar.change(groupName, delta);
                        }
                    }
                    this.change = change;
                    this.inc= function (groupName, val){
                        change(groupName, normilize(val));
                    };
                    this.dec= function (groupName, val){
                        change(groupName, -1*normilize(val));
                    };
                    this.info = function(){
                        var dt  = [];
                        $.each(settings.groups, function(i, group){
                            dt.push({
                                'name' : group.name.toLowerCase().replace(' ', ''),
                                'label' : group.name,
                                'absvalue' : data[group.name],
                                'percentage' : data[group.name]/sum*100
                            })
                        });
                        var done=0;
                        $.each(completion_groups, function(i, group_name){
                            done += data[group_name];
                        });
                    
                        return {intervals : dt, done : Math.round(done/sum)};
                    };
                }

                function PopupManager(){
                    function closePopup(){
                        $.fn.colorbox.close();
                        return false;
                    }
                    function openPopup(url){
                        $.fn.colorbox( { href: url, open: true})
                    }

                    function createNewTicket(story){
                        window.popup_context = {
                            cancel : closePopup,
                            setup  :function (root){
                                var milestone = (wbcontext.board=='stories') ? story.summary : wbcontext.milestone;
                                var milestoneInput = $("[name='field_milestone']", root);
                                milestoneInput.val(milestone);
                                if(milestoneInput.length>0){
                                    var htmlElem = milestoneInput.get(0);
                                    if(typeof htmlElem.refresh=='function'){
                                        htmlElem.refresh();
                                    }
                                }
                                $("[name='field_type']", root).val(settings.workitem.types[0]);
                            },
                            done : function(ticket){
                                log('popup reports that action was done', ticket);
                                var storyId = story.id;
                                if(typeof storyId=='undefined'){
                                    storyId='';
                                }
                                ctx.managers.transport.proxy.ticketconfig.trace(
                                    function(resp){
                                        if(isScopeItem(ticket)){
                                            renderer.renderScopeElement(ticket);
                                        }else{
                                            story.add(ticket);
                                            renderer.renderScopeElement(story);
                                        }
                                    },
                                    ticket.id,
                                    storyId
                                )
                                return closePopup();
                            }
                        };
                        openPopup(settings.baseurl+'/popup/ticket');
                    }

                    function comment(ticket, a){
                        window.popup_context = {
                            cancel : closePopup,
                            setup  : function (root){},
                            done   : function(tkt){
                                log('popup reports that action was done', tkt);
                                return closePopup();
                            }
                        }
                        openPopup(a.href);
                    }

                    function edit(ticket, a){
                        window.popup_context = {
                            cancel : closePopup,
                            setup  : function (){},
                            done   : function(updatedTicket){
                                log('popup reports that action was done', ticket);
                                var story = ticket.story;
                                story.add(updatedTicket);
                                renderer.renderScopeElement(story);
                                return closePopup();
                            }
                        }
                        openPopup(a.href);
                    }
                    
                    function popup(a){
                        openPopup(a.href);
                    }
                    
                    this.createNewTicket = createNewTicket;
                    this.comment = comment;
                    this.edit = edit;
                    this.popup = popup;
                }

                function readTickets(){
                    log('reading out tickets for context', wbcontext);
                    ctx.managers.transport.proxy.whiteboard.query(
                        function(resp){
                            log('Whiteboard query results:', resp);

                            $.each(resp.result, function(i, story){
                                decorateScopeElement(story, i);
                                if (typeof story.references!='undefined'){
                                    $.each(story.references, function(j, ticket){
                                        story.add(ticket);
                                    });
                                }
                                stories[story.id]=story;
                            });
                            
                            renderStories();
                        },
                        wbcontext
                    );
                }
                
                function updateTicket(ticket, attrs, updateUI){
                    ctx.managers.transport.proxy.ticket.update(
                        function(resp){
                            log('Ticket update results:', resp);
                            if(resp.result){
                                var ticketId = resp.result[0], updatedTicket = resp.result[3];
                                updatedTicket.id = ticketId;
                                updatedTicket.story = ticket.story;
                                tickets[''+ticketId] = updatedTicket;
                                if(updateUI){
                                    var story = ticket.story;
                                    story.add(updatedTicket);
                                    renderer.renderScopeElement(story);
                                }
                            }
                        },
                        ticket.id,
                        '',
                        attrs
                    );
                }
                
                
                function renderStories(){
                    $.each(stories, function(id, story){
                        renderer.renderScopeElement(story);
                    });
                }
                
                function init(){
                    if(wbcontext.board=='burndown'){
                        renderer.renderBurndown();
                    }else{
                        readTickets();
                    }
                }

                ctx.addListener(init);
                ctx.reportReady(this);
                
                this.reset = reset;
                this.init = init;
                this.readTickets = readTickets;
                this.renderStories = renderStories;
            }

            new TransportManager();
            new TicketManager();
            
            var publicMethods = {
                'reset' : function(){
                    if(isInitialized){
                        ctx.managers.tickets.reset();
                        ctx.managers.tickets.init();
                    }
                },
                'redraw' : function(){
                    if(isInitialized){
                        ctx.managers.tickets.renderStories();
                    }
                }
            };
            $.data(document, 'whiteboard'+root.attr('id'), publicMethods);
            
            return this;
        },
        outerHTML : function() {
            return $('<div>').append(this.eq(0).clone()).html();
        }
    });
})(jQuery);