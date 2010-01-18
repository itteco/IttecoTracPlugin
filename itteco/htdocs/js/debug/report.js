function log(){
    if(typeof(console)!='undefined' && console.log){
        console.log.apply(console, arguments);
    }
}

function showPopup(ticket, popupName){
    function cancel(){
        $.fn.colorbox.close();
        return false;
    }

    window.popup_context = {
        cancel : cancel,
        setup  :function (root){},
        done : function(tkt){
            log('popup reports that action was done', tkt);
            return cancel();
        }
    }

    $.fn.colorbox(
        {
            href: './../popup/'+popupName+'/'+ticket,
            open: true,
            title: 'Edit Ticket'
        }
    )

}
function showQuickEditor(ticket){
    showPopup(ticket,'tickets');
}
function showCommentEditor(ticket){
    showPopup(ticket,'comment');
}
function showFullEditor(ticket){
    document.location = './../ticket/'+ticket;
}

(function($){
    
    $.fn.extend({
        executableGroup : function(options){
            var dragHelper = '<div id="dragHelper"><div>Dragging <span class="quantity">0</span> tickets.</div></div>';
            var defaults = {
                drop_box_items_selector : '#dropbox .content .report-result',
                all_tickets_selector : '.listing tbody td.ticket',
                draggable_options : {
                    helper:function(e){return $(dragHelper).get();}, 
                    opacity: 0.8, 
                    start: function(e, ui){
                        $('.quantity', ui.helper).text($(":checked").length || 1);
                    }
                },
                groupItemsContainer : function(header){
                    return $(header).next();
                }
            };
            
            var options = $.extend(defaults, options);
            function log(){
                if (options.debug && typeof console!='undefined'){
                    console.log.apply("", arguments);
                }
            }
            function ContextMenu() {
                $('body').append('<div id="inline-menu"><div id="inline-menu-body"></div></div>');
                
                var inlineMenu 		= $('#inline-menu');
                var inlineMenuBody 	= $('#inline-menu-body');
                // show menu
                function showInlineMenu(element) {
                    log('element', element, $(element));
                    offset = $(element).offset();
                    inlineMenu.css('left',offset.left);
                    inlineMenu.css('top',offset.top);
                    menuItems = getInlineMenu(element);
                    if (menuItems) {
                        inlineMenuBody.html('<div>' + $(element).outerHTML() + '</div>' + menuItems);
                        inlineMenu.show();	
                    }
                }
                
                // get menu items
                function getInlineMenu(element) {
                    var ticket = $(element).text().substr(1);
                    if ($(element).hasClass('ticket-pointer')) {
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
                
                attach($('.ticket-pointer'));
                
                $(inlineMenu).hover(
                    function(event) {},
                    function(event) {
                        $(inlineMenu).hide();
                    }
                );
            }

            var disableTickets = function(tkts){
                $(":checked", tkts).attr('disabled', 'disabled');
            }
            var enableTickets = function(tkts){
                $(":checked", tkts).removeAttr('disabled').attr('checked', false);
                $('td.ticket',tkts).draggable(options.draggable_options);
            };

            var getPattern = function(obj){
                var pattern = obj.text();
                obj.children().each(function(){
                    pattern = pattern.replace($(this).text(),'');
                });
                return pattern.replace(/\n\s*/, '');
            };
            
            var executeAjaxAction = function(tickets, target){
                var ids = $.map(tickets,function(tkt, i){return $('a',tkt).text().substring(1)});
                $.getJSON(document.location.pathname, {action: 'execute', tickets: ids.join(','), presets: target.attr('preset')}, 
                    function(data){ 
                        if (data && data.tickets){
                            var selectors = [];
                            $.each(data.tickets, function(){
                                selectors.push(' td.ticket[ticket="'+this+'"]');
                            });
                            var rows = $(selectors.join(','), '.listing tbody').parent().remove();
                            
                            var target_table = options.groupItemsContainer('.executableGroup[idx="'+target.attr('idx') +'"]');
                            if(target_table.length>0){
                                $('tbody', target_table).append(rows);
                            }else{
                                var sMatch = $('.numrows', target);
                                var s = sMatch.text().match(/\d+/);
                                var currQuantity = 0;
                                if (s){
                                    currQuantity = parseInt(s[0], 10);
                                }
                                sMatch.text(getMatchesText(currQuantity+rows.length));
                            }
                            calculateGroupMatches();
                            enableTickets(rows);
                        }
                    });
            };

            var dropTicketsToGroup = function(e, ui){
                var tkts = $(options.all_tickets_selector+':has(:checked)');
                if(tkts.length==0){
                    tkts = ui.draggable;
                }
                disableTickets(tkts)
                executeAjaxAction(tkts, $(this));
            };
            var decorateDropBox = function(){
                $('#dropbox .control-panel a').unbind('click').click(function(){
                    $('#dropbox .control-panel>*').add('#dropbox .content').toggle();
                });                
            }

            var decorateDropBoxItems = function(sel){
                var o = $(sel);
                o.each(function(i){
                    var dropBoxGroup = $(this);
                    dropBoxGroup.attr('pattern', getPattern(dropBoxGroup));
                    dropBoxGroup.attr('idx', 'group_'+i);
                    if($('.move-here', dropBoxGroup).length==0){
                        dropBoxGroup.droppable(
                            {
                                accept: '.ticket',
                                activeClass: 'droppable-active',
                                hoverClass: 'droppable-hover', 
                                drop: dropTicketsToGroup
                            }
                        );                        
                        dropBoxGroup.prepend('<div class="move-here">&#x00BB;</div>');
                        
                        $('.move-here', dropBoxGroup).click(function(){
                            var tkts = $('.listing tbody td.ticket:has(:checked)');
                            if(tkts.length>0){
                                disableTickets(tkts);
                                executeAjaxAction(tkts, $(this).parent());
                            }
                        });
                    }
                });
            };

            var setupGroup = function(group){
                var g = $(group);
                g.addClass('executableGroup');
                var matchingDropBoxItem = $(options.drop_box_items_selector + '[pattern="'+getPattern(group)+'"]');
                if(matchingDropBoxItem.length==1){
                    g.attr('idx', matchingDropBoxItem.attr('idx'));
                }
            };

            var decorateTickets = function(itemsContainer){
                var tkts = $('td.ticket', itemsContainer);
                tkts.css('cursor','move').prepend('<input type="checkbox"/>');
                var contextMenu = new ContextMenu();
                contextMenu.attachTo($('a', tkts).addClass('ticket-pointer'));
                tkts.each(function(i){
                    var t = $(this);
                    var tkt_id = $('a', t).text().substring(1);
                    t.attr('ticket', tkt_id);
                });
                tkts.draggable(options.draggable_options);
            };
            
            var getMatchesText = function(cnt){
                var txt = '(No matches)';
                if (cnt>0){
                    if(cnt==1){
                        txt = '(1 match)';
                    }else{
                        txt = '('+cnt+' matches)';
                    }
                }
                return txt;
            };
            
            var calculateGroupMatches= function(){
                var dropBoxGroups= $(options.drop_box_items_selector);
                
                $('.executableGroup').each(function(i){
                    var o = $(this);
                    var txt = getMatchesText($('td.ticket', options.groupItemsContainer(o)).length);
                    $('.numrows', o).text(txt);
                    $('.numrows', dropBoxGroups.filter('[idx="'+o.attr('idx') +'"]')).text(txt);
                });
            };
            
            decorateDropBox();
            decorateDropBoxItems(options.drop_box_items_selector);
            
            return this.each(function(){
                var o = options;
                setupGroup($(this));
                decorateTickets(o.groupItemsContainer(this));
            });
        },
        outerHTML : function() {
            return $('<div>').append(this.eq(0).clone()).html();
        }
    });
})(jQuery);

$(document).ready(function(){
    $('#content h2.report-result').executableGroup();
});
