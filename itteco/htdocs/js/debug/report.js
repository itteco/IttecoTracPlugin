function log(){
    if(typeof(console)!='undefined' && console.log){
        console.log(arguments);
    }
}

(function($){
    
    $.fn.extend({
        executableGroup : function(options){
            
            if (typeof options == 'string') {
                var args = Array.prototype.slice.call(arguments, 1);
                var res = $.data(document, 'executableGroup')[options].apply(this, args);
                if (res != undefined) {
                    return res;
                }
                return this;
            }
            
            var dragHelper = '<div id="dragHelper"><div>Dragging <span class="quantity">0</span> tickets.</div></div>';
            var ctx = {
                selectedTickets : [], 
                groups : {}
            };
            var defaults = {
                drop_box_items_selector : '#dropbox .content .report-result',
                all_tickets_selector : '.listing tbody tr',
                rpcurl: '/login/xmlrpc',
                draggable_options : {
                    helper:function(e){return $(dragHelper).get();}, 
                    opacity: 0.8,
                },
                groupItemsContainer : function(header){
                    return $(header).next();
                },
                selectionCallback : function(){},
                debug: false
            };
            
            var options = $.extend(defaults, options);
            var rpc = $.rpc(
               options.rpcurl,
               "xml",
               function(server) {
                    if(!server || !server.system) {
                        alert("Could not get the rpc object ..");
                        return;
                    }
                    log('rpc initialized');
                }
            );
            function log(){
                if (options.debug){
                    console.log.apply(console, arguments);
                }
            }
            log('created instance of excutable group for', this);

            function disableTickets(ids){
                $.each(ids, function(i, id){
                    $(':chekbox:checked[value="'+id+'"]').attr('disabled', 'disabled');
                });
            }
            function enableTickets(ids){
                $.each(ids, function(i, id){
                    var cb = $(':chekbox:[value="'+id+'"]');
                    cb.removeAttr('disabled').attr('checked', false);
                    decorateCheckbox(cb, id);
                    decorateTicket($('td.ticket[ticket="'+id+'"]'), id);
                });
            };

            function executeAjaxAction(tickets, groupName){
                log('executeAjaxAction', tickets, groupName);
                var group = ctx.groups[groupName];
                var target = group.element;
                ctx.selectedTickets = [];
                options.selectionCallback(ctx.selectedTickets.length>0, ctx.selectedTickets);
                rpc.ticketconfig.apply_preset(
                    function(resp){ 
                        var tickets = resp.result.tickets;
                        if (tickets){
                            var selectors = [];
                            $.each(tickets, function(){
                                selectors.push(' td.ticket[ticket="'+this+'"]');
                            });
                            var rows = $(selectors.join(','), $('.listing tbody')).parent();
                            log('removing rows', rows);
                            var target_table = options.groupItemsContainer(group.ticketsElement);
                            if(target_table.length>0){
                                rows.appendTo($('tbody', target_table));
                            }else{
                                rows.remove();
                                var sMatch = $('.numrows', target);
                                var s = sMatch.text().match(/\d+/);
                                var currQuantity = 0;
                                if (s){
                                    currQuantity = parseInt(s[0], 10);
                                }
                                sMatch.text(getMatchesText(currQuantity+rows.length));
                            }
                            calculateGroupMatches();
                            enableTickets(tickets);
                        }
                    },
                    tickets,
                    group.preset
                );
            };


            function decorateDropBox(){
                $('#dropbox .control-panel a').unbind('click').click(function(){
                    $('#dropbox .control-panel>*').add('#dropbox .content').toggle();
                });                
            }
            
            function getSelectedTickets(){
                log('selectedTickets are', ctx.selectedTickets);
                return ctx.selectedTickets;
            }
            
            function assignSelectionToGroup(groupName){
                log('dropped tickets', ctx.selectedTickets, groupName, getSelectedTickets());
                disableTickets(ctx.selectedTickets)
                executeAjaxAction(ctx.selectedTickets, groupName);
            }

            function decorateDropBoxItems(sel){
                log('decorateDropBoxItems', sel);
                var o = $(sel);
                o.each(function(i){
                    var dropBoxGroup = $(this);
                    var groupName = $('.exec-group-name',dropBoxGroup).text();
                    ctx.groups[groupName] = {
                        name : groupName,
                        preset : dropBoxGroup.attr('preset'),
                        element: dropBoxGroup
                    }
                    dropBoxGroup.attr('idx', 'group_'+i);
                    dropBoxGroup.droppable(
                        {
                            accept: '.ticket',
                            activeClass: 'droppable-active',
                            hoverClass: 'droppable-hover', 
                            drop: function(e, ui){
                                assignSelectionToGroup(groupName);
                            }
                        }
                    );                        
                });
            };

            function setupGroup(g){
                g.addClass('executableGroup');
                var groupName = $('.exec-group-name', g).text();
                var group = ctx.groups[groupName];
                log('setting up group ', groupName, group);
                if(group){
                    ctx.groups[groupName].ticketsElement = g;
                    var tableLocator = options.groupItemsContainer(g);
                    $('thead tr', tableLocator).prepend('<th class="t-right t-s t-check"/>');
                    decorateTickets(tableLocator);
                }
            };
            
            function decorateTicket(ticket, tkt_id){
                ticket.draggable(
                    $.extend(
                        options.draggable_options, 
                        {
                            start: function(e, ui){
                                if(ctx.selectedTickets.length==0){
                                    ctx.selectedTickets.push(tkt_id);
                                }
                                $('.quantity', ui.helper).text(ctx.selectedTickets.length);
                            },
                            cancel: function(e, ui){
                                if(ctx.selectedTickets.length==1
                                    && $(':chekbox:checked[value="'+tkt_id+'"]').length==0){
                                        log('canceling selection');
                                    ctx.selectedTickets= [];
                                }
                            }
                        }
                    )
                );
                ticket.parent().removeClass('selected');
            }
            
            function decorateCheckbox(checkbox, tkt_id){
                checkbox.click(function(){
                    if($(this).is(':checked')){
                        ctx.selectedTickets.push(tkt_id);
                    }else{
                        ctx.selectedTickets = $.grep(ctx.selectedTickets, function(item, i){
                            log('grep', item, tkt_id);
                            return item != tkt_id;
                        });
                    }
                    log('selectedTickets', tkt_id, ctx.selectedTickets);
                    $(this).parent().parent().toggleClass('selected');
                    options.selectionCallback(ctx.selectedTickets.length>0, ctx.selectedTickets);
                });
            }

            function decorateTickets(itemsContainer){
                var tkts = $('td.ticket', itemsContainer);
                tkts.css('cursor','move');

                $('a', tkts).addClass('ticket-pointer');
                tkts.each(function(i){
                    var t = $(this), checkbox;
                    var tkt_id = $('a', t).text().substring(1);
                    t.attr('ticket', tkt_id);
                    t.before($('<td/>').append(checkbox = $('<input type="checkbox" value="'+tkt_id+'"/>')));
                    decorateCheckbox(checkbox, tkt_id);
                    decorateTicket(t, tkt_id);
                });
            };
            
            function getMatchesText(cnt){
                var txt = 'No matches';
                if (cnt>0){
                    if(cnt==1){
                        txt = '1 match';
                    }else{
                        txt = ''+cnt+' matches';
                    }
                }
                return txt;
            };
            
            function calculateGroupMatches(){
                $.each(ctx.groups, function(i, group){
                    if(group.ticketsElement){
                        var txt = getMatchesText($('td.ticket', options.groupItemsContainer(group.ticketsElement)).length);
                        $('.numrows', group.ticketsElement).text(txt);
                        $('.numrows', group.element).text(txt);

                    }
                });
            };
            
            decorateDropBox();
            decorateDropBoxItems(options.drop_box_items_selector);
            
            var publicMethods = {
                'assign' : function(groupName){
                    assignSelectionToGroup(groupName);
                },
            };
            $.data(document, 'executableGroup', publicMethods);

            
            return this.each(function(){
                var o = options;
                log('enabling executable groups for', this, options);
                setupGroup($(this));
            });
        },
        outerHTML : function() {
            return $('<div>').append(this.eq(0).clone()).html();
        }
    });
})(jQuery);