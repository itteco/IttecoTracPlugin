(function($) {
    $.fn.eventCalendar= function(options) {
        
        var settings = $.extend({}, $.fn.eventCalendar.defaults,  {target:this}, options);

        var ctx = {
            managersQuantity :4,
            managers : {},
            reportReady: function(manager){
                this.managers[manager.name]=manager;
                var cnt  =0;
                for(m in this.managers){
                    cnt = cnt +1;
                }
                if(cnt==this.managersQuantity){
                    if (typeof this['listeners'] !='undefined'){
                        for (idx in this.listeners){
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
    
        function notifyUIChanges(){
            if($.isFunction(settings.renderCallback)){
                settings.renderCallback();
            }
        }
        window.popup_context = {};
        function log(){
            if(settings.debug && typeof(console)!='undefined' && console.log){
                console.log.apply(console, arguments);
            }
        }
        log('pre init', this, options, settings);
        function TransportManager(){
            this.name = 'transport';
            var pointer = this;
            log('init TransportManager with ', settings.systemUrl);
            $.rpc(
               settings.systemUrl,
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
                
        function CalendarsManager(){
            this.name='calendars';
            var currentCalendar, calendars = {};
            var themeManager = new ThemeManager();
            var calContainers = {
                my : $(settings.my),
                shared: $(settings.shared)
            };
        
            function ThemeManager(){
                this.name = 'theme';
                var pointer = this;
                var cMenu, themeSelector, actions, del, share, edit;
                $('body').append(cMenu=$('<div class="c-menu" style="display:none;">').append(themeSelector=$('<ul id="theme-selector" class="c-menu-colors"/>')));
                for(var i=0; i<21; i++){
                    themeSelector.append($('<li><a href="#" class="c-color'+i+'" theme="'+i+'">#</a></li>'));
                }
                
                cMenu.append(actions=$('<ul class="c-menu-actions">')
                                .append(del = $('<li class="c-menu-item-delete"><a href="#">Delete</a></li>'))
                                .append(share = $('<li><a href="#">Share</a></li>'))
                                .append(edit= $('<li><a href="#">Edit</a></li>')));
                            

                this.attach = function(obj, cal, callback){
                    log('attaching calendar menu', cal);
                    var o = $(obj);
                    var offset = o.offset();
                    cMenu.hide().css('top',offset.top).css('left',offset.left - cMenu.width()).fadeIn(250);

                    themeSelector.find('li > a').unbind().click(function(){
                        setCalendarTheme(cal, $(this).attr('theme'));
                        pointer.hide();
                        return false;
                    });

                    $('a', edit).unbind().click(function(){
                        function noop(){}
                        function cancel(){
                            $.fn.colorbox.close();
                            pointer.hide();
                            return false;
                        }
                        popup_context = {
                            setup  : noop,
                            cancel : cancel,
                            done: function(respCal){
                                updateLocalCalendar(respCal);
                                return cancel();
                            }
                        }
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/calendars/'+cal.id,
                                open: true,
                                title: 'Calendar Data'
                            }
                        )

                    });

                    if(cal.own){
                        del.show();
                        share.show();
                        $('a', del).unbind().click(function(){
                            deleteCalendar(cal);
                            pointer.hide();
                            return false;
                        });
                        $('a', share).unbind().click(function(){
                            cal.type='S';
                            saveCalendar(cal);
                            pointer.hide();
                            return false;
                        });
                    }else{
                        del.hide();
                        share.hide();
                    }
                    
                    $(document).one('click', function(){
                        cMenu.hide();
                    });
                    cMenu.show();
                    return false;
                }
                this.hide= function(){
                    themeSelector.find('li > a').andSelf().unbind();
                    cMenu.hide();
                }
            }

            log('init CalendarsManager', calContainers);
            
            function initContainers(){
                $('.s-icon-calendar-add').click(function(){
                    function noop(){}
                    function cancel(){
                        $.fn.colorbox.close();
                        return false;
                    }
                    popup_context = {
                        setup  : noop,
                        cancel : cancel,
                        done: function(respCal){
                            updateLocalCalendar(respCal);
                            return cancel();
                        }
                    }
                    $.fn.colorbox(
                        {
                            href: settings.rootUrl+'/popup/calendars/',
                            open: true,
                            title: 'Calendar Data'
                        }
                    )
                });
            }
            function updateLocalCalendar(cal){
                var cals = [];
                cals.push(cal);
                consumeCalendarsData(cals);
                renderCalendars();
                ctx.managers.events.rerenderEvents(cal.id);
            }
            
            function readCalendars(){
                ctx.managers.transport.proxy.calendar.query(
                    function(resp){
                        log('getCalendars-result:',resp);
                        consumeCalendarsData(resp.result);
                        renderCalendars();
                        ctx.managers.events.init();
                });
            }
            
            function deleteCalendar(calendar){
                function delAndRender(cid){
                    delete calendars[cid];
                    renderCalendars();
                    ctx.managers.events.rerenderEvents();
                }
                
                if(typeof calendar.pid !='undefined'){
                    delAndRender(calendar.pid);
                    return;
                }
                ctx.managers.transport.proxy.calendar.remove(
                    function(){
                        delAndRender(calendar.id);
                    },
                    calendar.id
                );
            }
            
            function saveCalendar(calendar){
                ctx.managers.transport.proxy.calendar.save(
                    function(resp){
                        if(typeof calendar.pid !='undefined'){
                            delete calendars[calendar.pid];
                        }
                        log('saveCalName-resp', resp);
                        var cals = [], cal =resp.result;
                        cals.push(cal);
                        consumeCalendarsData(cals);
                        renderCalendars();
                        ctx.managers.events.rerenderEvents(cal.id);
                    },
                    calendar.id || '',
                    calendar.name,
                    calendar.theme,
                    calendar.type,
                    calendar.ref || 0
                );
            }

            function adjustRefCalendars(){
                $.each(calendars, function(){
                    if(this.type=='R'){
                        var refCal = calendars[this.ref];
                        refCal.theme = this.theme;
                        refCal.disabled = false;
                    };
                });
            }
            function consumeCalendarsData(cals){
                $.each(cals, function(){
                    this.disabled = !this.own;
                    calendars[this.id]=this;
                });
                adjustRefCalendars();
            }
            
            function setCalendarTheme(cal, theme){
                if(cal.theme == theme){
                    return;
                }
                var c, type;
                if (!cal.own){
                    type = 'R';
                    $.each(calendars, function(){
                        if(this.type=='R' && this.ref==cal.id){
                            c = this;
                            return true;
                        }
                    })
                }else{
                    c = cal;
                    type = c.type;
                }
                saveCalendar(
                    {
                        id : (c && c.id) || '',
                        name : cal.name,
                        type : type,
                        theme : theme,
                        ref : cal.id
                    }
                );

            }

            function renderCalendars(){
                for (var i in calContainers){
                    calContainers[i].empty();
                }

                $.each(calendars, function(){
                    var calendar = this;
                    if (calendar.type=='R'){
                        return true;
                    }
                    var cont = calendar.own 
                        ? calContainers.my
                        : calContainers.shared;
                    if(!currentCalendar && calendar.own){
                        currentCalendar = calendar;
                    }
                    var item, calNameElem, trigger;
                    cont.append(item=$('<li id="calendar_'+this.id+'" class="calendar-line'+
                        ' c-color' +this.theme+
                        (this.disabled ? ' c-non-selected' : ' c-selected')+
                        (currentCalendar===calendar ? ' calendar-editable' : '')+'"></li>')
                            .append(trigger=$('<a href="#" class="c-mlink">#</a>'))
                            .append(calNameElem=$('<span>'+this.name+'</span>')));
                        
                    calNameElem.click(function(){
                        item.toggleClass('c-selected').toggleClass('c-non-selected');
                    });
                    
                    trigger.unbind().click(function(){
                        var o = $(this);
                        themeManager.attach(o, calendar);
                        return false;
                    });           
                });
                notifyUIChanges();
            }
            this.read = readCalendars;
            this.getCalendar= function(){
                if(arguments.length==0){
                    return currentCalendar;
                }
                return calendars[arguments[0]];
            }
            initContainers();
            ctx.addListener(readCalendars);
            ctx.reportReady(this);
        }
        
        function Multicall(){
            var callbacks = [];
            var calls = [];
            
            this.push = function(){
                function noop(){}
                if (arguments.length>0){
                    var sliceLen = arguments.length-1;
                    var func = arguments[sliceLen];
                    if(typeof func != 'function'){
                        func = noop;
                    }else{
                        sliceLen = sliceLen -1;
                    }
                    if(arguments.length>1){
                        calls.push(
                            {
                                methodName: arguments[0],
                                params: $.grep(arguments, function(elem, idx){
                                    return idx != 0 && idx<=sliceLen;
                                })
                            }
                        );
                    }    
                    callbacks.push(func);
                }
            }
            
            this.call = function(){
                ctx.managers.transport.proxy.system.multicall(
                    function(resp){
                        var res = resp.result, len = resp.result.length;
                        $.each(callbacks, function(i, callback){
                            var obj;
                            if(i<len){
                                obj = res[i][0][3];
                            }
                            callback(obj);
                        });
                    },
                    calls
                );
            };
        }
        
        function TicketsManager(){
            this.name = 'tickets';
            var tickets = {};
            
            function Menu(){
                var tMenu, pointer = this;
                
                $('body').append(tMenu=$(
                    '<div class="t-menu" style="display:none;">'+
                        '<ul class="s-icon-bar">'+
                            '<li><a href="#" class="s-icon-button s-icon s-icon-comments" title="Comments">Comments</a></li>'+
                            '<li><a href="#" class="s-icon-button s-icon s-icon-edit" title="Full view/edit">Edit</a></li>'+
                            '<li><a href="#" class="s-icon-button s-icon s-icon-edit-quick" title="Quick view/edit">View</a></li>'+
                            '<li><a href="#" class="s-icon-button s-icon s-icon-create-event" title="Create event for this ticket">&#x00AB;</a></li>'+
                        '</ul>'+
                    '</div>'
                ));
            
                this.attach = function(obj, ticket){
                    log('attaching ticket menu', ticket);
                    var o = $(obj);
                    var offset = o.offset();
                    tMenu.hide().css('top',offset.top).css('left',offset.left - tMenu.width()).fadeIn(250);
                    
                    tMenu.find('li > a').unbind();

                    function noop(){}
                    function closePopup(){
                        $.fn.colorbox.close();
                        pointer.hide();
                        return false;
                    }

                    $('.s-icon-edit', tMenu).attr('href', settings.rootUrl+'/ticket/'+ticket.id);
                    $('.s-icon-comments', tMenu).click(function(){
                        popup_context = {
                            setup  : noop,
                            cancel : closePopup,
                            done: closePopup
                        }
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/comment/'+ticket.id,
                                open: true,
                                title: 'Comment Ticket'
                            }
                        )

                    });
                    
                    $('.s-icon-edit-quick', tMenu).click(function(){
                        popup_context = {
                            setup  : noop,
                            cancel : closePopup,
                            done: closePopup
                        }
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/tickets/'+ticket.id,
                                open: true,
                                title: 'Edit Ticket'
                            }
                        )

                    });
                    
                    $('.s-icon-create-event', tMenu).click(function(){
                        popup_context = {
                            setup  : noop,
                            cancel : closePopup,
                            done: function(res){
                                ctx.managers.events.renderEvent(res);
                                return closePopup();
                            }
                        }

                        var currentCalendar = ctx.managers.calendars.getCalendar();
                        var calId = currentCalendar && currentCalendar.id || '';
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/events/?calendar='+calId+'&ticket='+ticket.id+'&date='+(Math.ceil(new Date().getTime()/30/60/1000)*30*60),
                                open: true,
                                title: 'Create Event'
                            }
                        )

                    });

                    $(document).one('click', function(){
                        tMenu.hide();
                    });
                    tMenu.show();
                    return false;
                }
                this.hide= function(){
                    tMenu.hide();
                }

            }
            
            var menu = new Menu();
            
            log('init TicketsManager');
            
            function initContainer(){
                $('.s-icon-ticket-add').unbind().click(function(){
                    function noop(){}
                    function cancel(){
                        $.fn.colorbox.close();
                        return false;
                    }
                    popup_context = {
                        setup  : noop,
                        cancel : cancel,
                        done: function(ticket){
                            tickets[ticket.id]=ticket;
                            appendTicket($(settings.tickets),ticket);
                            return cancel();
                        }
                    }
                    $.fn.colorbox(
                        {
                            href: settings.rootUrl+'/popup/ticket/',
                            open: true,
                            title: 'Create Ticket'
                        }
                    )
                });
            }

            function readActiveTickets(){
                ctx.managers.transport.proxy.ticketconfig.my_active_tickets(
                    function(resp){
                        var multicall = new Multicall();
                        $.each(resp.result, function(i, o){
                            log('read-ticket-header', o);
                            var tkt_id = o.ticketId;
                            multicall.push('ticket.get', tkt_id, function(tkt){
                                tkt.id = tkt_id;
                                tickets[tkt_id] =tkt;
                            });
                        });
                        multicall.push(renderTickets);
                        multicall.call();         
                    }
                );
            }
            
            function appendTicket(container, ticket){
                var tktElem, menu_trigger;
                container.append(tktElem = $('<li id="ticket_'+ticket.id+'"/>')
                    .append(menu_trigger=$('<a href="#" class="c-mlink">#</a>'))
                    .append('<span><strong><a href="'+settings.rootUrl+'/ticket/'+ticket.id+'">#'+ticket.id+'</a></strong> '+ticket.summary+'</span>')
                );
            
                menu_trigger.click(function(){
                    menu.attach(this, ticket);
                    return false;
                });
            }
            function renderTickets(){
                var c = $(settings.tickets);
                $.each(tickets, function(id,ticket){
                    appendTicket(c, ticket);
                });
                notifyUIChanges();
            }
            
            initContainer();
            ctx.addListener(readActiveTickets);
            ctx.reportReady(this);        
        }
        
        function EventManager(){
            this.name= 'events';
            var fullCalendar;
            function toTimestamp(date){
                return Math.round(date.getTime() / 1000);
            }

            function mapDtoToCalEvent(dto, calEvent){
                if(typeof calEvent =='undefined'){
                    calEvent = {};
                }
                for(p in dto){
                    calEvent[p] = dto[p];
                }
                if(typeof (dto.start)!='object'){
                    calEvent.start = $.fullCalendar.parseISO8601(dto.start || '', false);
                }
                if(typeof (dto.end)!='object'){
                    calEvent.end= $.fullCalendar.parseISO8601(dto.end || '', false);
                }
                
                calEvent.title = dto.name;
                var calendar = ctx.managers.calendars.getCalendar(dto.calendar);
                if(calendar){
                    if(calendar.type!='R'){
                        calEvent.editable= true;
                    }
                    calEvent.className=[
                        'c-color'+calendar.theme, 
                        (dto.timetrack ? ' timetrac-enabled' : ''),
                        (dto.ticket && dto.ticket>0 ? ' ticket-reference' : '')
                    ];
                }
                
                log('mapped-event', calEvent, dto);
                return calEvent;
            }
            
            function readEvents(start, end, callback) {
                var events = [];
                ctx.managers.transport.proxy.event.query(
                    function(resp) {
                        log('events-resp', resp);
                        $.each(resp.result, function(){
                            events.push(mapDtoToCalEvent(this));
                        });
                        callback(events);
                    },
                    toTimestamp(start),
                    toTimestamp(end),
                    ctx.tzoffset
                );
            }

            
            function serializeAndSaveEvent(calEvent){
                ctx.managers.transport.proxy.event.save(
                    function(resp){
                        renderEvent(resp.result);
                    },
                    calEvent.id, 
                    calEvent.calendar,
                    calEvent.title, 
                    calEvent.allDay, 
                    calEvent.start,
                    calEvent.end,
                    calEvent.description,
                    calEvent.ticket,
                    calEvent.timetrack,
                    calEvent.auto,
                    calEvent.time,
                    ctx.tzoffset
                );
            }
            
            function renderEvent(event){
                var calEvent = fullCalendar.fullCalendar('clientEvents', event.id);
                if(calEvent){
                    calEvent = calEvent[0];
                }
                calEvent = mapDtoToCalEvent(event, calEvent);
                fullCalendar.fullCalendar('renderEvent',calEvent);
                calEvent.source = readEvents;
            }
            
            function setupPopupContext(){
                function noop(){}
                function cancel(){
                    $.fn.colorbox.close();
                    return false;
                }
                popup_context = {
                    setup  : noop,
                    cancel : cancel,
                    done: function(res){
                        renderEvent(res);
                        return cancel();
                    }
                }
            }
            
            
            function renderCalendar(){
                log('rendering fullCalendar', settings.target);
                fullCalendar = $(settings.target).fullCalendar({
                    editable: false,
                    disableDragging: false,
                    disableResizing: false,
                    firstHour : 8,
                    header: {
                        left: 'prev,next today',
                        center: 'title',
                        right: 'month,agendaWeek,agendaDay'
                    },
                    eventRender: function(calEvent, element, view){
                        var cal = ctx.managers.calendars.getCalendar(calEvent.calendar);
                        return (cal && !cal.disabled);            
                    },
                    loading: function(bool) {
                        if (bool) $('#loading').show();
                        else $('#loading').hide();
                    },
                    dayClick: function(dayDate, allDay, jsEvent, view){
                        setupPopupContext();
                        var currentCalendar = ctx.managers.calendars.getCalendar();
                        var calId = currentCalendar && currentCalendar.id || '';
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/events/?allDay='+allDay+'&calendar='+calId+'&date='+toTimestamp(dayDate),
                                open: true,
                                title: 'Create Event'
                            }
                        )
                    },                    
                    eventClick: function(calEvent, jsEvent, view){
                        setupPopupContext();
                        $.fn.colorbox(
                            {
                                href: settings.rootUrl+'/popup/events/'+calEvent.id,
                                open: true,
                                title: 'Edit Event'
                            }
                        )

                    },
                    eventDrop : function(calEvent, dayDelta, minuteDelta, allDay, revertFunc, jsEvent, ui, view){
                        log('eventDrop', calEvent, dayDelta, minuteDelta, allDay);
                        serializeAndSaveEvent(calEvent);
                    }, 
                    eventResize: function(calEvent, dayDelta, minuteDelta, revertFunc, jsEvent, ui, view){
                        serializeAndSaveEvent(calEvent);           
                    },
                    viewDisplay : function(view){
                        notifyUIChanges();
                    }
                });   
            }
            
            this.renderEvent = renderEvent;
            
            this.rerenderEvents = function(calId){
                log('rerenderEvents', calId);
                if(calId){
                    $.each(
                        fullCalendar.fullCalendar('clientEvents', function(e){
                            return e.calendar == calId;
                        }),
                        function(i, e){
                            fullCalendar.fullCalendar('updateEvent', mapDtoToCalEvent(e,e));
                        }
                    );
                }
                fullCalendar.fullCalendar('rerenderEvents');
            }
            
            this.init= function(){
                renderCalendar();
                fullCalendar.fullCalendar('addEventSource',readEvents);
            }
                       
            ctx.reportReady(this);        
        }
        
        function testDraggable(){
            //test of the dragging tickets
            $('.fc-view td').droppable(
                {
                    accept:'#demo',
                    tolerance : 'pointer',
                    hoverClass : 'droppable-hover', 
                    over : function(){log('over', this); this.old_bg =$(this).css('backgound'); $(this).css('background','#90e224 url(./../images/droppable-hover.png) 0 0');},
                    out : function(){log('out', this); $(this).css('background', this.old_bg);},
                    drop : function (){log('drop')}
                }
            );
            $('.help').click(function(){
                var view  = fullCalendar.fullCalendar('getView');
                log('view',view);
                view.reportEventElement({_id: 'ticket_1'},$('#ticket_1'));
                view.draggableEvent({_id: 'ticket_1'},$('#ticket_1'));
            });
            
        }
        

        //init managers- each will land in ctx.managers
        new TransportManager();
        new CalendarsManager();
        new TicketsManager();
        new EventManager();

    };
    
    // publicly accessible defaults
    $.fn.eventCalendar.defaults = {
        my       : '#my-calendars',
        shared   : '#shared-calendars',
        tickets  : '#tickets',
        debug    : false
    };

})(jQuery);
