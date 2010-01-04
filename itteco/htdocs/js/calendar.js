(function($) {
    $.fn.eventCalendar= function(options) {
        
        var settings = $.extend({}, $.fn.eventCalendar.defaults,  {target:this}, options);

        var ctx = {
            managersQuantity :5,
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
            debug : true
        };
        window.popup_context = {};
        function log(){
            if(settings.debug && console && console.log){
                console.log.apply(console, arguments);
            }
        }
        log('pre init', this, options, settings);
        function ThemeManager(){
            this.name = 'theme';
            var pointer = this;
            var themeSelector, timerId;
            $('body').append(themeSelector=$('<ul id="theme-selector" class="theme-selector" style="position:absolute;display:none;"/>'));
            for(var i=0; i<7; i++){
                themeSelector.append($('<li class="event-theme-'+i+'" theme="'+i+'"><div class="toggler">&nbsp;</div></li>'));
            }
            function setupHiderTimer(){
                timerId = setTimeout(
                    function(){
                        pointer.hide();
                    },
                    500
                );
            }
            
            function clearHiderTimer(){
                clearTimeout(timerId);
            }
            
            this.attach = function(obj,cal, callback){
                var o = $(obj);
                o.one('mouseleave', function(){
                    setupHiderTimer();
                });
                themeSelector.bind('mouseenter', function(){
                    clearHiderTimer();
                }).bind('mouseleave',function(){
                    setupHiderTimer();
                });
                
                themeSelector.find('li').click(function(){
                    callback($(this).attr('theme'));
                    pointer.hide();
                });
                themeSelector.css(
                        {
                            top: o.offset().top, 
                            left: o.offset().left
                        }
                ).show();
            }
            this.hide= function(){
                themeSelector.find('li').andSelf().unbind();
                themeSelector.hide();
            }
            
            ctx.reportReady(this);
        }

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
            var calContainers = {
                my : $(settings.my),
                myShared: $(settings.myShared),
                shared: $(settings.shared)
            };
        
            log('init CalendarsManager', calContainers);
        
            function createDummyCalendar(type){
                if(typeof type =='undefined'){
                    type = 'P';
                }
                return {
                    pid   : new Date().getTime(),
                    type  : type, 
                    name  : '&lt;change me&gt;', 
                    theme : 1, 
                    own   : true,
                    ref   : 0
                }
            }
        
            function renderCreators(){
                var elem;
                calContainers.my.before(elem=$('<a href="#add">add</a>'));
                function createHandler(type){
                    return function(){
                        var c = createDummyCalendar(type);
                        calendars[c.pid]=c;
                        renderCalendars();
                    }
                }
                elem.click(createHandler('P'));
                calContainers.myShared.before(elem=$('<a href="#add">add</a>'));
                elem.click(createHandler('S'));
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
                ctx.managers.transport.proxy.calendar.delete(
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
                    calendar.id,
                    calendar.name,
                    calendar.theme,
                    calendar.type,
                    calendar.ref
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
                        ? (calendar.type=='S' ? calContainers.myShared : calContainers.my)
                        : calContainers.shared;
                    if(!currentCalendar && calendar.own){
                        currentCalendar = calendar;
                    }
                    var item, calNameElem, toggler, themeToggler, remover;
                    cont.append(item=$('<li id="calendar_'+this.id+'" class="calendar-line'+
                        ' event-theme-' +this.theme+
                        (this.disabled ? ' calendar-disabled' : '')+
                        (currentCalendar===calendar ? ' calendar-editable' : '')+'"></li>')
                            .append(toggler=$('<input type="checkbox" checked="'+
                                (calendar.enabled ? 'checked' :'') +
                                '" name="toggle-calendar-'+calendar.id+'"/>'))
                            .append(calNameElem=$('<span class="calendar-item">'+this.name+'</span>'))
                            .append(themeToggler=$('<span class="toggler">&nbsp;</span>'))
                            .append(remover= calendar.own ? $('<span class="remover">&nbsp;</span>') : '&nbsp;'));
                    if(calendar.own){
                        calNameElem.editable(function(value, options){
                            calendar.name = value;
                            saveCalendar(calendar);
                            return value;
                        });
                        
                        remover.click(function(){
                            deleteCalendar(calendar);
                        });
                    }
                    
                    themeToggler.click(function(){
                        var o = $(this);
                        ctx.managers.theme.attach(o, calendar, function(theme){
                            setCalendarTheme(calendar, theme);
                        });
                    });
                    toggler.change(function(){
                        calendar.disabled = !this.checked;
                        item.toggleClass('calendar-disabled', calendar.disabled);
                        ctx.managers.events.rerenderEvents(calendar.id);
                    });                    
                });        
            }
            this.read = readCalendars;
            this.getCalendar= function(){
                if(arguments.length==0){
                    return currentCalendar;
                }
                return calendars[arguments[0]];
            }
            renderCreators();
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
            function readActiveTickets(){
                ctx.managers.transport.proxy.ticket.query(
                    function(resp){
                        var multicall = new Multicall();
                        $.each(resp.result, function(i, tkt_id){
                            multicall.push('ticket.get', tkt_id, function(tkt){
                                tickets[tkt_id] =tkt;
                            });
                        });
                        multicall.push(renderTickets);
                        multicall.call();         
                    }
                );
            }
            
            function renderTickets(){
                var c = $(settings.tickets);
                for(id in tickets){
                    var tktElem;
                    c.append(tktElem = $('<li id="ticket_'+id+'" class="ticket"> #'+id+' '+tickets[id].summary+'</li>'));
                    //tktElem.draggable();
                }
            }
            
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
                
                calEvent.title = dto.name;
                var calendar = ctx.managers.calendars.getCalendar(dto.calendar);
                if(calendar){
                    if(calendar.type!='R'){
                        calEvent.editable= true;
                    }
                    calEvent.className=[
                        'event-theme-'+calendar.theme, 
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
                    tb_remove();
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
                        tb_show(null, settings.rootUrl+'/popup/events/?allDay='+allDay+'&calendar='+calId+
                            '&date='+toTimestamp(dayDate)+
                            '&height=500&width=600', null);
                    },
                    eventClick: function(calEvent, jsEvent, view){
                        setupPopupContext();
                        tb_show(null, settings.rootUrl+'/popup/events/'+calEvent.id+'?height=500&width=600', null);        
                    },
                    eventDrop : function(calEvent, dayDelta, minuteDelta, allDay, revertFunc, jsEvent, ui, view){
                        log('eventDrop', calEvent, dayDelta, minuteDelta, allDay);
                        serializeAndSaveEvent(calEvent);
                    }, 
                    eventResize: function(calEvent, dayDelta, minuteDelta, revertFunc, jsEvent, ui, view){
                        serializeAndSaveEvent(calEvent);           
                    }
                });   
            }

            
            function showEventPopup(data){
            }
            
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
            
            this.showEventPopup = showEventPopup;
            
            ctx.reportReady(this);        
        }
               
        function fixPositioning(){
            var c = $('.fc-content', $(settings.target));
            //c.css('top', -150);
        }
        fixPositioning();
        
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
        new ThemeManager();
        new TransportManager();
        new CalendarsManager();
        new TicketsManager();
        new EventManager();

    };
    
    // publicly accessible defaults
    $.fn.eventCalendar.defaults = {
        my       : '#my-calendars',
        myShared : '#my-shared-calendars',
        shared   : '#shared-calendars',
        tickets  : '#tickets',
        debug    : false
    };

})(jQuery);
