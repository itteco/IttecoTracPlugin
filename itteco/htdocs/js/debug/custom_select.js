toggleDD=function(obj){    
    var o=$(obj); 
    o.next().css('width', o.parent().attr('clientWidth')).toggle().resizable();
    if(o.next(":visible").length>0){
        o.bind('reset',null, function(e){var o =$(this);var val=o.siblings(":hidden:last").val();o.siblings(":hidden").val(val);o.text(val)});
        $("li>div",o.next()).bind('mouseover',null,mouse_in_out).bind('mouseout',null,mouse_in_out).bind('click',null,clickDDI);
        o.next().add(o).bind('mouseout', null, 
            function(e){
                $(document).one('click',null, function(e){toggleDD(obj)});
            }).bind('mouseover', null,
            function(e){
                $(document).unbind('click');
            })
    }else{
        o.next().add(o).unbind('mouseout').unbind('mouseover');
        $(document).unbind('click');
    }
}    
mouse_in_out=function(event){$(this).toggleClass('focused_drop_down_item');}
clickDDI=function(event){
    var o = $(this);
    var par = o.parents(".custom_drop_down_box");
    
    $("li>div",par).removeClass('selected_drop_down_item');
    o.addClass('selected_drop_down_item');
    
    var field = par.prev();
    field.val(o.children('span:first').text() || '');
    toggleDD(field);
}