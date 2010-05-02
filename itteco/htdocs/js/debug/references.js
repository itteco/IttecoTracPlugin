(function($) {
    $.fn.ticketReferences= function(options) {

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

        var settings = $.extend({}, $.fn.ticketReferences.defaults,  {target:$(this)}, options);
        
        function log(){
            if (settings.debug && typeof console!='undefined'){
                console.log.apply("", arguments);
            }
        }

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

        function ReferencesManager(){
            this.name = 'references';
            log('init ticket manager');
            var candidates = {}, candidatesQuantity = 0, activeCandidate;
            var active = {};
            
            function initSearcher(){
                var form = $('form', $(settings.searchSelector));
                log('searcher form', form);
                form.submit(function(){
                    $(settings.searchProgressSelector).show();
                    $(settings.searchResultsSelector).hide();
                    
                    var filters = [];
                    $('input:checkbox:checked', form).each(function(){
                        filters.push(this.name);
                    });
                    ctx.managers.transport.proxy.ticketconfig.references_search(
                        function(resp){
                            $(settings.searchProgressSelector).hide();
                            $(settings.searchResultsSelector).show();

                            log('references search results', resp);
                            if(resp.result){
                                candidatesQuantity = -1;
                                candidates = {};
                                $.each(resp.result, function(i, result){
                                    candidatesQuantity=i;
                                    candidates[result.id] = result;
                                });
                                candidatesQuantity = candidatesQuantity +1;
                                renderResults();
                            }
                        },
                        $('input[name="q"]', form).val(),
                        filters
                    );
                    return false;
                });
            }

            function initActiveElements(){
                var dropArea = typeof(settings.dropTo)=='undefined' 
                    ? settings.target 
                    : $(settings.dropTo, settings.target);
                dropArea.droppable(
                    {
                        activeClass: 'droppable-active', 
                        hoverClass: 'droppable-hover',
                        drop: function(event, ui){
                            log('the dropped candidate id', activeCandidate);
                            renderTraceItem(activeCandidate, $(settings.appendTarget));
                            setTimeout(function(){
                                $(ui.draggable).draggable('destroy');
                            },
                            200);
                        }
                    }
                );
                $('li', settings.target).each(function(){
                    var ref = $(this);
                    active[$(':hidden', ref).val()] = ref;
                    makeRemovable(ref);
                });
            }
            
            function makeRemovable(item){
                $('.t-trace-delete', item).click(function(){
                    delete active[$(':hidden', item).val()];
                    item.remove();
                    return false;
                });

            }
            
            function init(){
                initActiveElements();
                initSearcher();
            }
            
            function renderTraceItem(item, target){
                var item = $('<li>'+
                    '<input type="hidden" name="'+item.type+'_links" value="'+item.id+'"/>'+
                    '<a href="'+settings.baseurl+'/'+item.type+'/'+item.id+'" class="s-context s-icon-context s-icon s-icon-context-ticket">#'+item.id+'</a>'+ 
                    item.title+'<a href="#" class="t-trace-delete" title="Delete reference">delete</a>'+
                '</li>');
                target.append(item);
                makeRemovable(item);
                log('renderTraceItem', item, target);
            }
            
            function renderResults(){
                
                var summary = $(settings.searchSummarySelector);
                var results = $(settings.searchResultsSelector);
                
                results.empty();
                summary.html('Search for References &mdash;'+ candidatesQuantity +' items found');
                $.each(candidates, function(id, candidate){
                    results.append(createWidget(candidate));
                });
            }
            function createWidget(candidate){
                var widget = $(
                    '<div class="w-ticket w-ticket-'+candidate.subtype+' reference-'+candidate.type+' s-widget-nofx">'+
                        '<div class="w-ticket-header">'+
                            '<h6>'+
                                '<span class="w-ticket-number"><a href="'+settings.baseurl+'/'+candidate.type+'/'+candidate.id+'">#'+candidate.id+'</a></span>&nbsp;'+candidate.title+
                            '</h6>'+
                        '</div>'+
                        '<div class="w-ticket-body">'+
                            '<div class="w-ticket-description">'+candidate.excerpt+'</div>'+
                            '<div class="s-columns w-ticket-toolbar">'+
                                '<div class="s-column-left">'+
                                    (candidate.author 
                                        ? '<div class="s-avatar-wrapper s-avatar-wrapper-20">'+
                                                '<img class="s-avatar" width="20" height="20" alt="'+candidate.author+'" title="'+candidate.author+'" src="'+settings.avatarResolver(settings, candidate.author)+'" />'+
                                            '</div>'
                                        : ''
                                    )+
                                    (candidate.date
                                        ? '<div class="w-ticket-values">'+candidate.date+'</div>'
                                        : ''
                                    )+
                                '</div>'+
                                '<div class="s-column-right">'+
                                    '<ul class="s-icon-bar">'+
                                        (candidate.type=='ticket' 
                                            ?
                                                '<li><a href="#" class="s-icon-button s-icon s-icon-edit-quick" title="Quick view/edit">View</a></li>'+
                                                '<li><a href="#" class="s-icon-button s-icon s-icon-edit" title="Full view/edit">Edit</a></li>'+
                                                '<li><a href="#" class="s-icon-button s-icon s-icon-comments" title="Comments">Comments</a></li>'
                                            : ''
                                        )+
                                    '</ul>'+
                                '</div>'+
                            '</div>'+
                        '</div>'+
                    '</div>');
                if($('input[value="'+candidate.id+'"]', settings.target).length==0){
                    widget.draggable(
                        {
                            helper : 'clone',
                            start: function(event, ui){
                                ui.helper.width(widget.width());
                                activeCandidate = candidate;
                            }
                        }
                    );
                }
                settings.rendererCallback(widget);
                return widget;
            }
            init();
            ctx.reportReady(this);
        }

        new TransportManager();
        new ReferencesManager();
    };
    // publicly accessible defaults
    $.fn.ticketReferences.defaults = {
        baseurl : '',
        rpcurl: '/login/xmlrpc',
        searchProgressSelector: '#search-reference-progress',
        searchSelector: '#trac-ticket-edit-search-references',
        searchSummarySelector: '#trac-ticket-edit-search-references-results .references-search-summary > h4',
        searchResultsSelector: '#trac-ticket-edit-search-references-results .references-search-results',
        appendTarget: '#trac-outgoing-links',
        avatarResolver: function(settings, owner){
            return settings.baseurl+'/chrome/itteco/images/avatar.png';
        },
        rendererCallback: function(widget){
        },
        debug    : false
    };

})(jQuery);


