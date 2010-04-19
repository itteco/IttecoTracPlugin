(function($){    
    $.fn.extend({
        editableReport: function(options){
            var rpc;
            var tickets ={};
            var defaults = {
                fields    : {
                    ticket: { editable: false }, 
                    description : { multiline : true }
                },
                delay     : 5000,
                rpcurl    : '/login/xmlrpc',
                timerurl  : '',
                debug     : false
            };
            var options = $.extend(defaults, options);
            function log(){
                if (options.debug && typeof console!='undefined'){
                    console.log.apply("", arguments);
                }
            }
            
            function PopupManager(){
                function showPopup(ticket, popupName){
                    function cancel(){
                        $.fn.colorbox.close();
                        return false;
                    }

                    window.popup_context = {
                        cancel : cancel,
                        setup  :function (root){},
                        done : function(tkt){
                            return cancel();
                        }
                    }

                    $.fn.colorbox(
                        {
                            href: './../popup/'+popupName+'/'+ticket,
                            open: true
                        }
                    )

                }
                function showQuickEditor(ticket){
                    showPopup(ticket,'ticket');
                }
                function showCommentEditor(ticket){
                    showPopup(ticket,'comment/ticket');
                }
                function showFullEditor(ticket){
                    document.location = './../ticket/'+ticket;
                }
                
                this.showQuickEditor=showQuickEditor;
                this.showCommentEditor=showCommentEditor;
                this.showFullEditor=showFullEditor;
            }
            
            function FieldsManager(){
                var defaultField = {
                    type : 'text',
                    editable: true,
                    options : {}
                }
                this.isEditable = function(name){
                    var field = options.fields[name];
                    if(typeof(field)=='undefined'){
                        return false;
                    }
                    return field.editable || defaultField.editable;
                }
                
                this.getFieldType = function(name){
                    var field = options.fields[name] || defaultField;
                    return field.type ||  defaultField.type;
                }
                
                this.getFieldOptions = function(name){
                    var empty = [''];
                    var field = options.fields[name] || defaultField;
                    var o = field.options ||  defaultField.options;
                    return empty.concat(o);
                }
                
                this.setFieldValue = function(ticket, fieldName, value){
                    value = value || '';
                    var field = options.fields[fieldName];
                    if(typeof(field)!='undefined'){
                        var o = field.options;
                        if(typeof(o)!='undefined' && typeof(ticket[field.field_name])!='undefined'){
                            //options are defined and it is not a first run
                            try{
                                var idx = parseInt(value, 10);
                                if(!isNaN(idx)){
                                    value = o[idx-1];
                                    log('selection value for index='+idx+' is '+value);
                                }
                            }catch(e){log('failed to convert to number')}
                        }
                        ticket[field.field_name]=value
                        return value;
                    }
                }
                this.getFieldValue = function(ticket, fieldName){
                    var field = options.fields[fieldName];
                    if(typeof(field)!='undefined'){
                        return ticket[field.field_name];
                    }
                }


            }
            
            function Queue(){
                var queue = {};
                var postponed = {};
                
                this.dequeue=function (tkt_id){
                    var timeOut = queue[tkt_id];
                    if(typeof timeOut!='undefined'){
                        log('dequeue-ticket', tkt_id);
                        delete queue[tkt_id];
                        clearTimeout(timeOut);
                        return true;
                    }
                    return false;
                }
                
                this.enqueue= function (tkt_id){
                    log('enqueue-ticket', tkt_id);
                    var pointer = this;
                    delete postponed[tkt_id];
                    this.dequeue(tkt_id);//postpone ticket saving if it is in queue
                    queue[tkt_id]=setTimeout(
                        function(){
                            pointer.dequeue(tkt_id);
                            saveTicket(tkt_id);
                        }, 
                        options.delay
                    );
                }
                this.postpone = function (tkt_id){
                    if(this.dequeue(tkt_id)){
                        log('postpone-ticket', tkt_id);
                        postponed[tkt_id] = true;
                    }
                }
                this.requeue = function (tkt_id){
                    if(postponed[tkt_id]){
                        log('requeue-ticket', tkt_id);
                        delete postponed[tkt_id];
                        this.enqueue(tkt_id);
                    }
                }


            }
            
            function setupRpc(url){
                rpc = $.rpc(
                   url,
                   "xml",
                   function(server) {
                        if(!server || !server.system) {
                            alert("Could not get the rpc object ..");
                            return;
                        }
                        log('rpc initialized');
                    }
                );
            }
            function trim(val){
                if(typeof val!='string'){
                    return val;
                }
                return  val.replace(/^\s+|\s+$/,'');
            }
            function saveTicket(tkt_id){
                var ticket = tickets[tkt_id];
                log('posting ticket content', ticket);
                rpc.ticket.update(
                    function(resp){
                        if(typeof(resp.result)!='undefined'){
                            log('ticket '+tkt_id+' saved');
                        }else{
                            log('saving failed. error string =', resp.error.faultString);
                        }
                    },
                    tkt_id,
                    '',
                    ticket
                );
            }
            setupRpc(options.rpcurl);
            var fieldsManager = new FieldsManager();
            var queue = new Queue();
            var popupManager = new PopupManager();
            return this.each(function(){
                var justSaved;
                $('table.tickets tbody tr', this).each(function(){
                    $row = $(this);
                    var tktPointer = $('td.ticket a',$row);
                    if(tktPointer.length==1){
                        var ticketHead = tktPointer.text().match(/#\d+/);
                        var ticketNum = parseInt(ticketHead[0].substr(1), 10);
                        log('found-ticket-number', ticketNum);
                        var ticket = {};
                        $('td', $row).each(function(){
                            var $col = $(this), $a = $('a', $col);
                            var html = $col.html(), aHtml = $a.outerHTML();
                            var names = $col.attr('class').split(' ');
                            var name = names[0];
                            var val = trim(trim($col.text()).replace('\n',''));
                            if(fieldsManager.isEditable(name)){
                                fieldsManager.setFieldValue(ticket, name, val);
                                var type = fieldsManager.getFieldType(name)
                                $col.editable(
                                    function(value, options){
                                        justSaved = $col;
                                        log('setting-ticket-field ', name,' to ', value,' for ticket',ticket);
                                        value = fieldsManager.setFieldValue(ticket, name, value);
                                        queue.enqueue(ticketNum);
                                        if($a.length>0){
                                            log('returning html as we have anchor');
                                            return html.replace(aHtml, $a.text(value).outerHTML());
                                        }
                                        return value;
                                    }, 
                                    {
                                        data : function(){
                                            if(type=='select'){
                                                return fieldsManager.getFieldOptions(name);
                                            }
                                            return fieldsManager.getFieldValue(ticket, name);
                                        },
                                        placeholder : '&lt;n/a&gt;',
                                        type : type,
                                        submit : '<a class="s-icon s-icon-inline-save t-inline-edit-button" title="Save" href="#">Save</a>',
                                        cancel : '<a class="s-icon s-icon-inline-cancel t-inline-edit-button" title="Cancel" href="#">Cancel</a>',
                                        onedit : function(){//do not save ticket, while we have editor open
                                            if(justSaved==$col){
                                                return false
                                            }
                                            queue.postpone(ticketNum);
                                        },
                                        onreset : function(){//save if we have changes pending
                                            queue.requeue(ticketNum);
                                        }
                                    }
                                );
                            }
                            if($col.is(':last-child')){
                                $col.addClass('t-menu');
                                $col.html(
                                    '<span>'+$col.html()+'</span>\n'+
                                    '<ul class="s-icon-bar" style="display: none;">'+
                                        '<li><a title="Quick view/edit" class="s-icon-button s-icon s-icon-edit-quick" href="#">View</a></li>'+
                                        '<li><a title="Full view/edit" class="s-icon-button s-icon s-icon-edit" href="#">Edit</a></li>'+
                                        '<li><a title="Comments" class="s-icon-button s-icon s-icon-comments" href="#">Comments</a></li>'+
                                        (options.timerurl!='' ? '<li><a href="'+options.timerurl+'?title='+encodeURIComponent('#'+ticket.id+' '+ ticket.summary)+'">Time Track</a></li>' : '')+
                                    '</ul>');
                                $col.find('.s-icon-edit-quick').click(function(){
                                    popupManager.showQuickEditor(ticketNum);
                                });
                                $col.find('.s-icon-edit').click(function(){
                                    popupManager.showFullEditor(ticketNum);
                                });
                                $col.find('.s-icon-comments').click(function(){
                                    popupManager.showCommentEditor(ticketNum);
                                });
                            }
                        });
                        log('ticket-object', ticket);
                        tickets[ticketNum] = ticket;
                        $row.hover(
                            function(){
                                var sitem = $(this);
                                sitem.addClass('hover');
                                setTimeout(function() {
                                        if (sitem.hasClass('hover')) {
                                            var menu = sitem.find('.s-icon-bar');
                                            menu.fadeIn();
                                            menu.parent().find('span').fadeOut('fast');
                                        }
                                    }, 500
                                );
                                
                            },
                            function(){
                                var sitem = $(this);
                                sitem.removeClass('hover');
                                var menu = sitem.find('.s-icon-bar');
                                menu.fadeOut('fast');
                                menu.parent().find('span').fadeIn('fast');
                            }
                        );

                    }
                });
                log('all-found-tickets', tickets);
            });
        },
        outerHTML : function() {
            return $('<div>').append(this.eq(0).clone()).html();
        }
    });
})(jQuery);